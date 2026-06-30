# Operator queue management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorder the operator history tabs and add experiment/action queue reorder+removal (enabled only when stopped AND the active sequence is manual), built by mirroring the existing `move_sequence`/`remove_sequence` stack.

**Architecture:** Four new domain deque mutators → four orch FastAPI routes → four backend port+adapter methods → operator buttons/callbacks gated on `stopped AND active_sequence.manual_action`, with `manual_action=True` now set on operator-built manual sequences and the history tabs reordered.

**Tech Stack:** Python 3.12, pydantic v2, FastAPI, Bokeh, pytest. Run tests via `conda run -n helao python -m pytest ...`.

## Global Constraints

- Framework only (`helao/framework/`).
- Every queue mutator mirrors the existing `move_sequence`/`remove_sequence` exactly (domain `orchestration.py:503/513`, route `orch_api.py:1551`, backend `ports/operator_backend.py:69` + `adapters/operator_backend.py:149`, operator `button_seq_*`/`callback_seq_*`). Out-of-range index = no-op.
- "Manual" = `active_sequence.manual_action is True`; set `manual_action=True` on the operator's `manual_orch_seq` wrapper in `append_experiment`/`prepend_experiment`. No new `get_orch_state` payload field (active_sequence dict already carries it).
- Experiment/action queue buttons enabled iff `loop_state == stopped AND active_sequence.manual_action`. Sequence-queue buttons keep their existing stopped-only gate (do NOT change).
- History-tab group order: `Planner, Sequence History, Experiment History, Action History`.
- Mutate only the pending deques (`experiment_dq`/`action_dq`), never the active object.
- Spec: `docs/superpowers/specs/2026-06-29-operator-queue-management-design.md`.

---

### Task 1: domain queue mutators for experiment_dq + action_dq

**Files:**
- Modify: `helao/framework/domain/orchestration.py` (after `remove_sequence` ~line 516)
- Test: `helao/framework/tests/test_domain_orchestration.py`

**Interfaces:**
- Produces: `move_experiment(state, from_idx, to_idx) -> OrchState`, `remove_experiment(state, idx) -> OrchState`, `move_action(state, from_idx, to_idx) -> OrchState`, `remove_action(state, idx) -> OrchState`.

- [ ] **Step 1: Write the failing tests**

Add to `helao/framework/tests/test_domain_orchestration.py` (after the existing dispatch/queue tests):

```python
def test_move_experiment_reorders_queue():
    e0, e1, e2 = RunExperiment(experiment_name="e0"), RunExperiment(experiment_name="e1"), RunExperiment(experiment_name="e2")
    st = _state(experiment_dq=[e0, e1, e2])
    orch.move_experiment(st, 2, 0)
    assert [e.experiment_name for e in st.experiment_dq] == ["e2", "e0", "e1"]
    orch.move_experiment(st, 5, 0)  # out of range -> no-op
    assert [e.experiment_name for e in st.experiment_dq] == ["e2", "e0", "e1"]


def test_remove_experiment_drops_item():
    e0, e1 = RunExperiment(experiment_name="e0"), RunExperiment(experiment_name="e1")
    st = _state(experiment_dq=[e0, e1])
    orch.remove_experiment(st, 0)
    assert [e.experiment_name for e in st.experiment_dq] == ["e1"]
    orch.remove_experiment(st, 9)  # out of range -> no-op
    assert [e.experiment_name for e in st.experiment_dq] == ["e1"]


def test_move_action_reorders_queue():
    a0, a1, a2 = _action(action_name="a0"), _action(action_name="a1"), _action(action_name="a2")
    st = _state(action_dq=[a0, a1, a2])
    orch.move_action(st, 0, 2)
    assert [a.action_name for a in st.action_dq] == ["a1", "a2", "a0"]
    orch.move_action(st, 0, 7)  # out of range -> no-op
    assert [a.action_name for a in st.action_dq] == ["a1", "a2", "a0"]


def test_remove_action_drops_item():
    a0, a1 = _action(action_name="a0"), _action(action_name="a1")
    st = _state(action_dq=[a0, a1])
    orch.remove_action(st, 1)
    assert [a.action_name for a in st.action_dq] == ["a0"]
    orch.remove_action(st, -3)  # out of range -> no-op (negative)
    assert [a.action_name for a in st.action_dq] == ["a0"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_domain_orchestration.py -k "move_experiment or remove_experiment or move_action or remove_action" -v`
Expected: FAIL — `orch` has no `move_experiment`/etc. (AttributeError).

- [ ] **Step 3: Add the mutators**

In `helao/framework/domain/orchestration.py`, immediately after `remove_sequence` (~line 516), add:

```python
def move_experiment(state: OrchState, from_idx: int, to_idx: int) -> OrchState:
    """Move the queued experiment at from_idx to to_idx; out-of-range is a no-op. Mirrors move_sequence."""
    dq = state.experiment_dq
    n = len(dq)
    if 0 <= from_idx < n and 0 <= to_idx < n:
        exp = dq.pop(from_idx)
        dq.insert(to_idx, exp)
    return state


def remove_experiment(state: OrchState, idx: int) -> OrchState:
    """Drop the queued experiment at idx; out-of-range no-op. Mirrors remove_sequence."""
    if 0 <= idx < len(state.experiment_dq):
        del state.experiment_dq[idx]
    return state


def move_action(state: OrchState, from_idx: int, to_idx: int) -> OrchState:
    """Move the queued action at from_idx to to_idx; out-of-range is a no-op. Mirrors move_sequence."""
    dq = state.action_dq
    n = len(dq)
    if 0 <= from_idx < n and 0 <= to_idx < n:
        act = dq.pop(from_idx)
        dq.insert(to_idx, act)
    return state


def remove_action(state: OrchState, idx: int) -> OrchState:
    """Drop the queued action at idx; out-of-range no-op. Mirrors remove_sequence."""
    if 0 <= idx < len(state.action_dq):
        del state.action_dq[idx]
    return state
```

If `orchestration.py` defines an `__all__`, add the four names to it (check; `move_sequence`/`remove_sequence` membership tells you whether it's maintained).

- [ ] **Step 4: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_domain_orchestration.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add helao/framework/domain/orchestration.py helao/framework/tests/test_domain_orchestration.py
git commit -m "feat(framework): domain mutators move/remove experiment+action queues"
```

---

### Task 2: orch endpoints for experiment/action queue mutators

**Files:**
- Modify: `helao/framework/app/orch_api.py` (after the `/remove_sequence` route ~line 1559)
- Test: `helao/framework/tests/test_app_orch_api.py`

**Interfaces:**
- Consumes: Task 1 domain mutators.
- Produces: routes `/move_experiment`, `/remove_experiment`, `/move_action`, `/remove_action` returning `{"n_experiments": ...}` / `{"n_actions": ...}`.

- [ ] **Step 1: Write the failing tests**

Add to `helao/framework/tests/test_app_orch_api.py` (uses the existing `_make_driver` fixture; `RunExperiment` is imported there — if not, import from `helao.framework.domain.run_models`):

```python
def test_driver_move_and_remove_experiment_via_domain():
    from helao.framework.domain.run_models import RunExperiment as _RE
    driver = _make_driver()
    driver.state.experiment_dq = [_RE(experiment_name="e0"), _RE(experiment_name="e1")]
    orch.move_experiment(driver.state, 1, 0)
    assert [e.experiment_name for e in driver.state.experiment_dq] == ["e1", "e0"]
    orch.remove_experiment(driver.state, 0)
    assert [e.experiment_name for e in driver.state.experiment_dq] == ["e0"]


def test_driver_move_and_remove_action_via_domain():
    from helao.framework.domain.run_models import RunAction as _RA
    driver = _make_driver()
    driver.state.action_dq = [_RA(action_name="a0"), _RA(action_name="a1")]
    orch.move_action(driver.state, 0, 1)
    assert [a.action_name for a in driver.state.action_dq] == ["a1", "a0"]
    orch.remove_action(driver.state, 0)
    assert [a.action_name for a in driver.state.action_dq] == ["a1"]
```

(`orch` = `helao.framework.domain.orchestration`, already imported in this test module as the driver's domain.)

- [ ] **Step 2: Run to verify they fail**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_orch_api.py -k "move_and_remove" -v`
Expected: FAIL — `orch.move_experiment`/etc. undefined until Task 1 is present. (If Task 1 already merged, these pass at the domain level; the ROUTE coverage is the new surface — proceed to add routes so the endpoints exist.)

- [ ] **Step 3: Add the routes**

In `helao/framework/app/orch_api.py`, immediately after the `/remove_sequence` route (~line 1559), add:

```python
    @app.post("/move_experiment")
    async def move_experiment(from_idx: int, to_idx: int) -> dict:
        orch.move_experiment(driver.state, from_idx, to_idx)
        return {"n_experiments": len(driver.state.experiment_dq)}

    @app.post("/remove_experiment")
    async def remove_experiment(idx: int) -> dict:
        orch.remove_experiment(driver.state, idx)
        return {"n_experiments": len(driver.state.experiment_dq)}

    @app.post("/move_action")
    async def move_action(from_idx: int, to_idx: int) -> dict:
        orch.move_action(driver.state, from_idx, to_idx)
        return {"n_actions": len(driver.state.action_dq)}

    @app.post("/remove_action")
    async def remove_action(idx: int) -> dict:
        orch.remove_action(driver.state, idx)
        return {"n_actions": len(driver.state.action_dq)}
```

- [ ] **Step 4: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_orch_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add helao/framework/app/orch_api.py helao/framework/tests/test_app_orch_api.py
git commit -m "feat(framework): orch endpoints move/remove experiment+action queues"
```

---

### Task 3: backend port + adapter methods

**Files:**
- Modify: `helao/framework/ports/operator_backend.py` (after `remove_sequence` ~line 72); `helao/framework/adapters/operator_backend.py` (after `remove_sequence` ~line 156)
- Test: `helao/framework/tests/test_adapters_operator_backend.py`

**Interfaces:**
- Produces: backend `move_experiment(from_idx, to_idx)`, `remove_experiment(idx)`, `move_action(from_idx, to_idx)`, `remove_action(idx)`; adapter issues the matching `_call(endpoint, params_dict)`.

- [ ] **Step 1: Write the failing test**

Add to `helao/framework/tests/test_adapters_operator_backend.py` (mirror the existing `move_sequence`/`remove_sequence` recording test — reuse its exact backend-with-recording-`_call` construction):

```python
def test_experiment_and_action_queue_calls():
    be, calls = _make_recording_backend()  # use the same construction the move_sequence test uses
    asyncio.run(be.move_experiment(2, 0))
    asyncio.run(be.remove_experiment(1))
    asyncio.run(be.move_action(0, 3))
    asyncio.run(be.remove_action(2))
    assert calls[0] == ("move_experiment", {"from_idx": 2, "to_idx": 0})
    assert calls[1] == ("remove_experiment", {"idx": 1})
    assert calls[2] == ("move_action", {"from_idx": 0, "to_idx": 3})
    assert calls[3] == ("remove_action", {"idx": 2})
```

(If that test file builds the backend inline rather than via a helper, replicate that inline construction here instead of `_make_recording_backend`.)

- [ ] **Step 2: Run to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_adapters_operator_backend.py::test_experiment_and_action_queue_calls -v`
Expected: FAIL — `move_experiment`/etc. not defined (AttributeError).

- [ ] **Step 3: Add the methods**

Port `helao/framework/ports/operator_backend.py` (after `remove_sequence` ~line 72), following the existing `@abstractmethod async def …: ...` style used by `move_sequence`/`remove_sequence`:

```python
    @abstractmethod
    async def move_experiment(self, from_idx: int, to_idx: int) -> None: ...

    @abstractmethod
    async def remove_experiment(self, idx: int) -> None: ...

    @abstractmethod
    async def move_action(self, from_idx: int, to_idx: int) -> None: ...

    @abstractmethod
    async def remove_action(self, idx: int) -> None: ...
```

Adapter `helao/framework/adapters/operator_backend.py` (after `remove_sequence` ~line 156):

```python
    async def move_experiment(self, from_idx, to_idx):
        await self._call(
            "move_experiment", params_dict={"from_idx": from_idx, "to_idx": to_idx}
        )

    async def remove_experiment(self, idx):
        await self._call("remove_experiment", params_dict={"idx": idx})

    async def move_action(self, from_idx, to_idx):
        await self._call(
            "move_action", params_dict={"from_idx": from_idx, "to_idx": to_idx}
        )

    async def remove_action(self, idx):
        await self._call("remove_action", params_dict={"idx": idx})
```

- [ ] **Step 4: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_adapters_operator_backend.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add helao/framework/ports/operator_backend.py helao/framework/adapters/operator_backend.py helao/framework/tests/test_adapters_operator_backend.py
git commit -m "feat(framework): operator backend move/remove experiment+action queues"
```

---

### Task 4: operator manual flag + history-tab reorder

**Files:**
- Modify: `helao/framework/app/operator/bokeh_operator.py` (`append_experiment`/`prepend_experiment` ~1861-1876; `planhistory_tabs` ~386-392)
- Test: `helao/framework/tests/test_app_operator.py`

**Interfaces:**
- Produces: operator-built `manual_orch_seq` sequences carry `manual_action=True`; history-tab order `Planner, Sequence History, Experiment History, Action History`.

- [ ] **Step 1: Write the failing tests**

Add to `helao/framework/tests/test_app_operator.py` (use the existing `_FakeVisOp(Document())` + `_MockBackend` pattern):

```python
def test_manual_wrap_sets_manual_action():
    from bokeh.document import Document
    from helao.framework.app.operator.bokeh_operator import BokehOperator
    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    op.append_experiment()
    assert op.plan[-1].manual_action is True
    op.prepend_experiment()
    assert op.plan[0].manual_action is True


def test_history_tab_order():
    from bokeh.document import Document
    from helao.framework.app.operator.bokeh_operator import BokehOperator
    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    titles = [t.title for t in op.planhistory_tabs.tabs]
    assert titles == ["Planner", "Sequence History", "Experiment History", "Action History"]
```

(If `populate_experimentmodel()` in `_MockBackend`'s context needs a selected experiment to wrap, set up the minimal selection the existing `test_plan_buffer_append_and_wrap` test uses before calling `append_experiment`; reuse that setup.)

- [ ] **Step 2: Run to verify they fail**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_operator.py -k "manual_wrap_sets or history_tab_order" -v`
Expected: FAIL — `manual_action` is False (not set); tab order is Action/Experiment/Sequence.

- [ ] **Step 3: Set manual_action on the wrap**

In `bokeh_operator.py`, in BOTH `append_experiment` and `prepend_experiment`, change the `Sequence(...)` construction to include `manual_action=True`:

```python
        seq = Sequence(
            sequence_name="manual_orch_seq",
            planned_experiments=[experimentmodel],
            manual_action=True,
        )
```

- [ ] **Step 4: Reorder the history tabs**

In `bokeh_operator.py`, change `planhistory_tabs` `tabs=[...]` (~386-392) to:

```python
        self.planhistory_tabs = Tabs(
            tabs=[
                self.planner_tab,
                self.sequence_history_tab,
                self.experiment_history_tab,
                self.action_history_tab,
            ],
            height_policy="min",
            sizing_mode="stretch_width",
        )
```

- [ ] **Step 5: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_operator.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add helao/framework/app/operator/bokeh_operator.py helao/framework/tests/test_app_operator.py
git commit -m "feat(framework): operator manual_action flag on manual seq + reorder history tabs"
```

---

### Task 5: operator experiment/action queue buttons + callbacks + gating

**Files:**
- Modify: `helao/framework/app/operator/bokeh_operator.py` (button defs ~462-469; callbacks ~1754-1784; Queues layout ~856; gating ~2635-2639)
- Test: `helao/framework/tests/test_app_operator.py`

**Interfaces:**
- Consumes: backend `move_experiment`/`remove_experiment`/`move_action`/`remove_action` (Task 3); `manual_action` flag (Task 4).
- Produces: `button_exp_move_up/down/remove`, `button_act_move_up/down/remove` + their callbacks; gated on `stopped AND manual`.

- [ ] **Step 1: Write the failing tests**

Add to `helao/framework/tests/test_app_operator.py`. First, ensure `_MockBackend` records the new calls — add to `_MockBackend.__init__` `self.queue_calls = []` and these methods:

```python
    async def move_experiment(self, from_idx, to_idx):
        self.queue_calls.append(("move_experiment", from_idx, to_idx))

    async def remove_experiment(self, idx):
        self.queue_calls.append(("remove_experiment", idx))

    async def move_action(self, from_idx, to_idx):
        self.queue_calls.append(("move_action", from_idx, to_idx))

    async def remove_action(self, idx):
        self.queue_calls.append(("remove_action", idx))
```

Then the tests:

```python
def test_exp_action_buttons_exist():
    from bokeh.document import Document
    from helao.framework.app.operator.bokeh_operator import BokehOperator
    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    for name in ("button_exp_move_up", "button_exp_move_down", "button_exp_remove",
                 "button_act_move_up", "button_act_move_down", "button_act_remove"):
        assert hasattr(op, name)


def test_exp_remove_callback_dispatches(monkeypatch):
    from bokeh.document import Document
    from helao.framework.app.operator.bokeh_operator import BokehOperator
    vis = _FakeVisOp(Document())
    be = _MockBackend()
    op = BokehOperator(vis, be)
    op.experiment_source.selected.indices = [0]
    op.experiment_source.data = {"experiment_name": ["e0", "e1"]}
    op.callback_exp_remove(None)
    _drain_callbacks(vis.doc)
    assert ("remove_experiment", 0) in be.queue_calls


def test_act_move_up_callback_dispatches():
    from bokeh.document import Document
    from helao.framework.app.operator.bokeh_operator import BokehOperator
    vis = _FakeVisOp(Document())
    be = _MockBackend()
    op = BokehOperator(vis, be)
    op.action_source.selected.indices = [1]
    op.action_source.data = {"action_name": ["a0", "a1"]}
    op.callback_act_move_up(None)
    _drain_callbacks(vis.doc)
    assert ("move_action", 1, 0) in be.queue_calls
```

- [ ] **Step 2: Run to verify they fail**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_operator.py -k "exp_action_buttons or exp_remove_callback or act_move_up_callback" -v`
Expected: FAIL — buttons/callbacks don't exist (AttributeError).

- [ ] **Step 3: Add the buttons**

In `bokeh_operator.py`, immediately after the `button_seq_*` definitions (~469), add:

```python
        self.button_exp_move_up = self._make_button(
            "ExpQ ↑", "default", 70, self.callback_exp_move_up, width_policy="min"
        )
        self.button_exp_move_down = self._make_button(
            "ExpQ ↓", "default", 70, self.callback_exp_move_down, width_policy="min"
        )
        self.button_exp_remove = self._make_button(
            "ExpQ ✕", "default", 70, self.callback_exp_remove, width_policy="min"
        )
        self.button_act_move_up = self._make_button(
            "ActQ ↑", "default", 70, self.callback_act_move_up, width_policy="min"
        )
        self.button_act_move_down = self._make_button(
            "ActQ ↓", "default", 70, self.callback_act_move_down, width_policy="min"
        )
        self.button_act_remove = self._make_button(
            "ActQ ✕", "default", 70, self.callback_act_remove, width_policy="min"
        )
```

- [ ] **Step 4: Add the callbacks**

In `bokeh_operator.py`, immediately after `callback_seq_remove` (~1784), add (mirroring the `callback_seq_*` bodies):

```python
    def callback_exp_move_up(self, event):
        idxs = list(self.experiment_source.selected.indices)
        if idxs and idxs[0] > 0:
            i = idxs[0]
            self.vis.doc.add_next_tick_callback(
                partial(self.backend.move_experiment, i, i - 1)
            )
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_exp_move_down(self, event):
        idxs = list(self.experiment_source.selected.indices)
        n = len(self.experiment_source.data.get("experiment_name", []))
        if idxs and idxs[0] < n - 1:
            i = idxs[0]
            self.vis.doc.add_next_tick_callback(
                partial(self.backend.move_experiment, i, i + 1)
            )
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_exp_remove(self, event):
        idxs = list(self.experiment_source.selected.indices)
        if idxs:
            i = idxs[0]
            self.vis.doc.add_next_tick_callback(
                partial(self.backend.remove_experiment, i)
            )
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_act_move_up(self, event):
        idxs = list(self.action_source.selected.indices)
        if idxs and idxs[0] > 0:
            i = idxs[0]
            self.vis.doc.add_next_tick_callback(
                partial(self.backend.move_action, i, i - 1)
            )
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_act_move_down(self, event):
        idxs = list(self.action_source.selected.indices)
        n = len(self.action_source.data.get("action_name", []))
        if idxs and idxs[0] < n - 1:
            i = idxs[0]
            self.vis.doc.add_next_tick_callback(
                partial(self.backend.move_action, i, i + 1)
            )
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_act_remove(self, event):
        idxs = list(self.action_source.selected.indices)
        if idxs:
            i = idxs[0]
            self.vis.doc.add_next_tick_callback(
                partial(self.backend.remove_action, i)
            )
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))
```

- [ ] **Step 5: Place the button rows in the Queues layout**

In `bokeh_operator.py`, in the Queues `layout([...])` block, immediately after the existing `row(self.button_seq_move_up, self.button_seq_move_down, self.button_seq_remove, spacing=4)` (~856-861), add two rows:

```python
                        row(
                            self.button_seq_move_up,
                            self.button_seq_move_down,
                            self.button_seq_remove,
                            spacing=4,
                        ),
                        row(
                            self.button_exp_move_up,
                            self.button_exp_move_down,
                            self.button_exp_remove,
                            spacing=4,
                        ),
                        row(
                            self.button_act_move_up,
                            self.button_act_move_down,
                            self.button_act_remove,
                            spacing=4,
                        ),
```

(Keep the existing seq row; add the two new rows directly below it.)

- [ ] **Step 6: Add the stopped+manual gating**

In `bokeh_operator.py`, in the state-update method, after the existing sequence-queue gating (~2635-2639):

```python
        self.button_seq_move_up.disabled = queue_disabled
        self.button_seq_move_down.disabled = queue_disabled
        self.button_seq_remove.disabled = queue_disabled
        manual_seq = bool((state.get("active_sequence") or {}).get("manual_action"))
        exp_act_disabled = queue_disabled or not manual_seq
        self.button_exp_move_up.disabled = exp_act_disabled
        self.button_exp_move_down.disabled = exp_act_disabled
        self.button_exp_remove.disabled = exp_act_disabled
        self.button_act_move_up.disabled = exp_act_disabled
        self.button_act_move_down.disabled = exp_act_disabled
        self.button_act_remove.disabled = exp_act_disabled
```

(`queue_disabled` already exists as `loop_state != LoopStatus.stopped.value`; `state` is the `get_orch_state()` payload already in scope at this point — confirm the local variable name holding the payload and use it.)

- [ ] **Step 7: Add a gating unit test**

Add to `helao/framework/tests/test_app_operator.py` a test that drives the update path with a stopped+manual state and asserts the exp/action buttons are enabled, and with stopped+non-manual that they are disabled. Use the same mechanism existing operator tests use to invoke the state-update method (find how `test_operator_tables_from_backend` triggers it — `_MockBackend.get_orch_state` returns the state dict; set `_MockBackend.loop_state="stopped"` and have its `get_orch_state` include `active_sequence={"manual_action": True}` vs `{}`). Mirror that existing invocation exactly:

```python
def test_exp_action_buttons_gated_on_stopped_and_manual():
    from bokeh.document import Document
    from helao.framework.app.operator.bokeh_operator import BokehOperator
    vis = _FakeVisOp(Document())
    be = _MockBackend()
    be.loop_state = "stopped"
    be.active_sequence = {"manual_action": True}   # add support in _MockBackend.get_orch_state
    op = BokehOperator(vis, be)
    _drain_callbacks(vis.doc)
    # trigger the update path the same way test_operator_tables_from_backend does, then:
    assert op.button_exp_remove.disabled is False
    assert op.button_act_remove.disabled is False

    be.active_sequence = {}  # not manual
    _drain_callbacks(vis.doc)
    # re-trigger update, then:
    assert op.button_exp_remove.disabled is True
```

Wire `_MockBackend.get_orch_state` to return `{"loop_state": self.loop_state, "active_sequence": getattr(self, "active_sequence", {}), "n_sequences": 0, "n_experiments": 0, "n_actions": 0}` so the gating predicate reads it. Match the actual update-trigger mechanism used by the existing operator tests; if the existing tests call a specific coroutine to refresh state, call it here too.

- [ ] **Step 8: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_operator.py -v`
Expected: PASS (whole file).

- [ ] **Step 9: Commit**

```bash
git add helao/framework/app/operator/bokeh_operator.py helao/framework/tests/test_app_operator.py
git commit -m "feat(framework): operator experiment/action queue buttons gated on stopped+manual"
```

---

### Task 6: full-suite regression check

**Files:** none (verification only).

- [ ] **Step 1: Run the full framework suite**

Run: `conda run -n helao python -m pytest helao/framework/tests -p no:warnings`
Expected: PASS — prior baseline 1673 passed, 28 skipped; now higher by the new tests, zero failures. Exact count may vary by ±a few; requirement is zero failures.

- [ ] **Step 2: If any pre-existing operator/orch test asserts the old tab order or an exact button-row layout**

Update that assertion to the new order/layout and commit with `test(framework): update operator assertions for new tab order / queue buttons`. Otherwise no commit needed.

---

## Self-Review

**Spec coverage:**
- D history-tab reorder → Task 4 ✓.
- E domain mutators → Task 1 ✓; orch endpoints → Task 2 ✓; backend port+adapter → Task 3 ✓; manual_action flag → Task 4 ✓; buttons+callbacks+layout+gating → Task 5 ✓.
- Gating predicate (stopped AND manual) → Task 5 Step 6/7 ✓; sequence buttons unchanged → Task 5 keeps existing seq gating ✓.
- Out-of-scope items (dispatch/expansion, active-object mutation) → absent ✓.
- Testing items from spec → Tasks 1-5 each carry matching tests ✓.

**Placeholder scan:** none — every code step shows complete code. The "match the existing test's construction/trigger mechanism" notes (Task 3 recording helper, Task 5 Step 7 update-trigger) are explicit instructions to mirror a named existing test, not deferrals.

**Type consistency:** `move_experiment(state, from_idx, to_idx)` / `remove_experiment(state, idx)` / `move_action` / `remove_action` signatures identical across domain (T1), endpoint calls (T2), backend (T3), and operator callbacks (T5). Endpoint return keys `n_experiments`/`n_actions` consistent. `manual_action` (bool) set in T4, read by gating predicate in T5. Button attribute names `button_exp_*`/`button_act_*` consistent between T5 defs, callbacks, layout, and gating.
