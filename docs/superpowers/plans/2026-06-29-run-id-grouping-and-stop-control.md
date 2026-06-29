# run_id grouping + stop-without-reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `sequence_order` (dispatch index within a run_id grouping) to `SequenceModel`, and an opt-in `reset_run_id`-on-stop control exposed through the orchestrator endpoint and a BokehOperator checkbox; plus relocate/rename the Clear-plan button.

**Architecture:** `sequence_order` mirrors the just-shipped `experiment_order`: a new `OrchState` counter stamped in `dispatch_sequence`, reset when `active_run_id` changes. `reset_run_id` threads a default-`False` flag domain→app→backend→operator; only the stop branch of `apply_intent` consults it. Operator changes are layout/label plus one CheckboxGroup.

**Tech Stack:** Python 3.12, pydantic v2, FastAPI, Bokeh, pytest. Run tests via `conda run -n helao python -m pytest ...`.

## Global Constraints

- Framework only (`helao/framework/`).
- `sequence_order: Optional[int] = 0` on the **full** `SequenceModel` (not `ShortSequenceModel`), mirroring `ExperimentModel.experiment_order`.
- `reset_run_id` defaults to `False` everywhere; default path = current behavior (stop does NOT reset `active_run_id`). Only the `("stop","intend_stop")` branch of `apply_intent` consults it. Do NOT change estop or `complete_idle`.
- Do NOT assign `seq.run_id` anywhere (no producer added).
- Operator: checkbox `CheckboxGroup(labels=["reset run_id"], active=[])` (unchecked) right of Stop Orch; Clear button label `"Clear expplan"`→`"Clear plan"` (attribute name `button_clear_expplan` unchanged) relocated immediately right of `button_prepend_plan`.
- Spec: `docs/superpowers/specs/2026-06-29-run-id-grouping-and-stop-control-design.md`.

---

### Task 1: `sequence_order` field on `SequenceModel`

**Files:**
- Modify: `helao/framework/models/sequence.py` (class `SequenceModel`, after `manual_action: bool = False` ~line 102; docstring block above)
- Test: `helao/framework/tests/test_models_aes.py`

**Interfaces:**
- Produces: `SequenceModel.sequence_order: Optional[int]` default `0`; inherited by `RunSequence`.

- [ ] **Step 1: Write the failing tests**

Add to `helao/framework/tests/test_models_aes.py` (after the existing sequence-model tests):

```python
def test_sequence_model_has_sequence_order_default():
    from helao.framework.models.sequence import SequenceModel
    sm = SequenceModel()
    assert sm.sequence_order == 0


def test_sequence_order_round_trips():
    from helao.framework.models.sequence import SequenceModel
    sm = SequenceModel(sequence_name="s", sequence_order=4)
    assert SequenceModel(**sm.model_dump()).sequence_order == 4
```

- [ ] **Step 2: Run to verify they fail**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_models_aes.py::test_sequence_model_has_sequence_order_default helao/framework/tests/test_models_aes.py::test_sequence_order_round_trips -v`
Expected: FAIL (round-trip asserts 4 but pydantic drops the unknown kwarg → default 0 / attribute missing).

- [ ] **Step 3: Add the field**

In `helao/framework/models/sequence.py`, in `SequenceModel`, add directly after `manual_action: bool = False`:

```python
    manual_action: bool = False
    sequence_order: Optional[int] = 0
```

Add the matching docstring attribute line in the `SequenceModel` Attributes block:

```python
        sequence_order (Optional[int]): Dispatch index of the sequence within its run_id grouping.
```

(`Optional` is already imported — `run_id: Optional[UUID]` uses it.)

- [ ] **Step 4: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_models_aes.py -v`
Expected: PASS (whole file).

- [ ] **Step 5: Commit**

```bash
git add helao/framework/models/sequence.py helao/framework/tests/test_models_aes.py
git commit -m "feat(framework): add sequence_order field to SequenceModel"
```

---

### Task 2: stamp `sequence_order` in `dispatch_sequence`

**Files:**
- Modify: `helao/framework/domain/orchestration.py` (`OrchState` field block ~188; `dispatch_sequence` run_id derivation ~1125-1130)
- Test: `helao/framework/tests/test_domain_orchestration.py`

**Interfaces:**
- Consumes: `SequenceModel.sequence_order` (Task 1); `OrchState.active_run_id`.
- Produces: `OrchState.active_run_seq_counter: int` (default 0); `seq.sequence_order` stamped at dispatch.

- [ ] **Step 1: Write the failing tests**

Add to `helao/framework/tests/test_domain_orchestration.py` (in the dispatch_sequence section, after `test_dispatch_sequence_retains_prior_as_last`):

```python
def test_dispatch_sequence_stamps_sequence_order_zero_first():
    seq = RunSequence(sequence_name="s0")
    st = _state(sequence_dq=[seq])
    st, _ = orch.dispatch_sequence(st, now=NOW, uuid=SEED)
    assert seq.sequence_order == 0
    assert st.active_run_seq_counter == 0


def test_dispatch_sequence_order_increments_within_same_run():
    s0 = RunSequence(sequence_name="s0")
    s1 = RunSequence(sequence_name="s1")
    st = _state(sequence_dq=[s0, s1])
    st, _ = orch.dispatch_sequence(st, now=NOW, uuid=SEED)        # seeds active_run_id
    st, _ = orch.dispatch_sequence(st, now=NOW, uuid=SEED)        # same run -> increment
    assert s0.sequence_order == 0
    assert s1.sequence_order == 1


def test_dispatch_sequence_order_resets_when_run_id_changes():
    s0 = RunSequence(sequence_name="s0")
    st = _state(sequence_dq=[s0])
    st, _ = orch.dispatch_sequence(st, now=NOW, uuid=SEED)
    assert s0.sequence_order == 0
    # a stop-with-reset (or estop) drops active_run_id -> next seq is a new run
    st.active_run_id = None
    s1 = RunSequence(sequence_name="s1")
    st.sequence_dq = [s1]
    st, _ = orch.dispatch_sequence(st, now=NOW, uuid=SEED)
    assert s1.sequence_order == 0
```

- [ ] **Step 2: Run to verify they fail**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_domain_orchestration.py -k "sequence_order" -v`
Expected: FAIL — `active_run_seq_counter` attribute does not exist / `sequence_order` never stamped.

- [ ] **Step 3: Add the counter field**

In `helao/framework/domain/orchestration.py`, in `OrchState`, add after `active_run_id: Optional[UUID] = None` (~line 189):

```python
    active_run_id: Optional[UUID] = None
    active_run_seq_counter: int = 0
```

Add a matching docstring line in the `OrchState` Attributes block near `active_run_id`:

```python
        active_run_seq_counter: Dispatch index of the active sequence within the current run_id grouping.
```

- [ ] **Step 4: Stamp in `dispatch_sequence`**

The existing run_id derivation block reads:

```python
    # derive the active run id from the sequence
    if getattr(seq, "run_id", None) is not None:
        state.active_run_id = seq.run_id
    elif state.active_run_id is None:
        state.active_run_id = seq.sequence_uuid
```

Capture the prior run id immediately ABOVE that comment, and add the counter/stamp immediately BELOW the block (before the `register_obj_uuid(` call):

```python
    # capture the run id before re-derivation to detect a run grouping change
    prior_run_id = state.active_run_id
    # derive the active run id from the sequence
    if getattr(seq, "run_id", None) is not None:
        state.active_run_id = seq.run_id
    elif state.active_run_id is None:
        state.active_run_id = seq.sequence_uuid

    # sequence_order = 0-indexed position within the run_id grouping. Increment
    # within the same run; reset to 0 when a new run_id begins (incl. the first
    # sequence after a stop-with-reset / estop dropped active_run_id to None).
    if state.active_run_id == prior_run_id:
        state.active_run_seq_counter += 1
    else:
        state.active_run_seq_counter = 0
    seq.sequence_order = state.active_run_seq_counter
```

- [ ] **Step 5: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_domain_orchestration.py -v`
Expected: PASS (whole file).

- [ ] **Step 6: Commit**

```bash
git add helao/framework/domain/orchestration.py helao/framework/tests/test_domain_orchestration.py
git commit -m "feat(framework): stamp sequence_order per run_id grouping at dispatch"
```

---

### Task 3: `reset_run_id` in `apply_intent`

**Files:**
- Modify: `helao/framework/domain/orchestration.py` (`apply_intent` signature ~634-636; stop branch ~683-686)
- Test: `helao/framework/tests/test_domain_orchestration.py`

**Interfaces:**
- Produces: `apply_intent(state, intent, *, reason="", reset_run_id: bool = False)`. When `intent in ("stop","intend_stop")` and `reset_run_id` is True, sets `state.active_run_id = None`.

- [ ] **Step 1: Write the failing tests**

Add to `helao/framework/tests/test_domain_orchestration.py` (in the apply_intent section, after `test_intend_stop_unconditional`):

```python
def test_stop_default_keeps_run_id():
    st = _state()
    st.active_run_id = uuid4()
    rid = st.active_run_id
    st, _ = orch.apply_intent(st, "stop")
    assert st.active_run_id == rid


def test_stop_with_reset_clears_run_id():
    st = _state()
    st.active_run_id = uuid4()
    st, _ = orch.apply_intent(st, "stop", reset_run_id=True)
    assert st.active_run_id is None


def test_intend_stop_with_reset_clears_run_id():
    st = _state()
    st.active_run_id = uuid4()
    st, _ = orch.apply_intent(st, "intend_stop", reset_run_id=True)
    assert st.active_run_id is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_domain_orchestration.py -k "run_id and (stop or intend)" -v`
Expected: FAIL — `apply_intent` has no `reset_run_id` kwarg (TypeError).

- [ ] **Step 3: Add the kwarg + reset**

Change the `apply_intent` signature (~line 634):

```python
def apply_intent(
    state: OrchState, intent: str, *, reason: str = "", reset_run_id: bool = False
) -> Tuple[OrchState, List[Command]]:
```

In the stop branch (~683):

```python
    elif intent in ("stop", "intend_stop"):
        if intent == "intend_stop" or gsm.loop_state == LoopStatus.started:
            gsm.loop_intent = LoopIntent.stop
        if reset_run_id:
            state.active_run_id = None
        cmds.append(_broadcast(state))
```

Add a line to the `apply_intent` docstring noting `reset_run_id` (under the `"stop"` bullet): "`reset_run_id=True` additionally drops `active_run_id` so the next sequence begins a new run grouping (default False)."

- [ ] **Step 4: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_domain_orchestration.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add helao/framework/domain/orchestration.py helao/framework/tests/test_domain_orchestration.py
git commit -m "feat(framework): apply_intent reset_run_id flag on stop (default off)"
```

---

### Task 4: orchestrator `stop` endpoint forwards `reset_run_id`

**Files:**
- Modify: `helao/framework/app/orch_api.py` (`OrchDriver._intent` ~568-571; `OrchDriver.stop` ~651-653; FastAPI routes `/{server_key}/stop` ~1443-1445 and `/stop` ~1638-1640)
- Test: `helao/framework/tests/test_app_orch_api.py`

**Interfaces:**
- Consumes: `apply_intent(..., reset_run_id=...)` (Task 3).
- Produces: `OrchDriver.stop(self, reset_run_id: bool = False)`; `_intent(self, intent, *, reason="", reset_run_id=False)`; both `stop` routes accept a `reset_run_id: bool = False` query param.

- [ ] **Step 1: Write the failing tests**

Add to `helao/framework/tests/test_app_orch_api.py` (uses the existing `_make_driver` fixture):

```python
def test_driver_stop_default_keeps_run_id():
    import uuid as _uuid
    driver = _make_driver()
    driver.state.active_run_id = _uuid.uuid4()
    rid = driver.state.active_run_id
    asyncio.run(driver.stop())
    assert driver.state.active_run_id == rid


def test_driver_stop_reset_clears_run_id():
    import uuid as _uuid
    driver = _make_driver()
    driver.state.active_run_id = _uuid.uuid4()
    asyncio.run(driver.stop(reset_run_id=True))
    assert driver.state.active_run_id is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_orch_api.py::test_driver_stop_reset_clears_run_id -v`
Expected: FAIL — `stop()` takes no `reset_run_id` argument (TypeError).

- [ ] **Step 3: Thread the flag through driver + routes**

`_intent` (~568):

```python
    async def _intent(self, intent: str, *, reason: str = "", reset_run_id: bool = False) -> None:
        _st, cmds = orch.apply_intent(self.state, intent, reason=reason, reset_run_id=reset_run_id)
        await self._execute(cmds)
```

`stop` (~651):

```python
    async def stop(self, reset_run_id: bool = False) -> None:
        """Request a graceful stop of the dispatch loop. ``reset_run_id`` also drops active_run_id."""
        await self._intent("stop", reset_run_id=reset_run_id)
```

Namespaced route (~1443):

```python
    @app.post(f"/{server_key}/stop")
    async def stop(reset_run_id: bool = False) -> dict:
        await driver.stop(reset_run_id=reset_run_id)
        return {"loop_state": getattr(driver.state.globalstatusmodel.loop_state, "value", str(driver.state.globalstatusmodel.loop_state))}
```

Root route (~1638):

```python
    @app.post("/stop")
    async def stop_root(reset_run_id: bool = False) -> dict:
        await driver.stop(reset_run_id=reset_run_id)
        return {"loop_state": getattr(driver.state.globalstatusmodel.loop_state, "value", str(driver.state.globalstatusmodel.loop_state))}
```

(If the existing route bodies return a different dict shape, KEEP their existing return value verbatim and only add the `reset_run_id: bool = False` param + pass it to `driver.stop`. Do not change the response contract.)

- [ ] **Step 4: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_orch_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add helao/framework/app/orch_api.py helao/framework/tests/test_app_orch_api.py
git commit -m "feat(framework): orch stop endpoint forwards reset_run_id"
```

---

### Task 5: operator backend `stop(reset_run_id)`

**Files:**
- Modify: `helao/framework/ports/operator_backend.py` (`stop` ~78); `helao/framework/adapters/operator_backend.py` (`stop` ~160-161)
- Test: `helao/framework/tests/test_adapters_operator_backend.py`

**Interfaces:**
- Produces: backend `stop(self, reset_run_id: bool = False)`; adapter issues `_call("stop", params_dict={"reset_run_id": reset_run_id})`.

- [ ] **Step 1: Write the failing test**

Add to `helao/framework/tests/test_adapters_operator_backend.py` (mirrors the existing `move_sequence`/`remove_sequence` `_call`-recording test ~105-108):

```python
def test_stop_forwards_reset_run_id_flag():
    be, calls = _make_recording_backend()
    asyncio.run(be.stop())
    asyncio.run(be.stop(reset_run_id=True))
    assert calls[0] == ("stop", {"reset_run_id": False})
    assert calls[1] == ("stop", {"reset_run_id": True})
```

(Use the same backend-with-recording-`_call` construction the existing `move_sequence` test uses; if that test builds the backend inline rather than via a helper, replicate that construction here instead of `_make_recording_backend`.)

- [ ] **Step 2: Run to verify it fails**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_adapters_operator_backend.py::test_stop_forwards_reset_run_id_flag -v`
Expected: FAIL — current `stop` calls `_call("stop")` with no params (`calls[0]` is `("stop", {})`), and `stop(reset_run_id=True)` raises TypeError.

- [ ] **Step 3: Add the param**

Port (`helao/framework/ports/operator_backend.py` ~78):

```python
    async def stop(self, reset_run_id: bool = False) -> None: ...
```

Adapter (`helao/framework/adapters/operator_backend.py` ~160):

```python
    async def stop(self, reset_run_id: bool = False):
        await self._call("stop", params_dict={"reset_run_id": reset_run_id})
```

- [ ] **Step 4: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_adapters_operator_backend.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add helao/framework/ports/operator_backend.py helao/framework/adapters/operator_backend.py helao/framework/tests/test_adapters_operator_backend.py
git commit -m "feat(framework): operator backend stop forwards reset_run_id"
```

---

### Task 6: BokehOperator — reset checkbox + Clear-plan relocate/rename

**Files:**
- Modify: `helao/framework/app/operator/bokeh_operator.py` (button defs ~471-481; `callback_stop_orch`; control-row layout ~774-779)
- Test: `helao/framework/tests/test_app_operator.py`

**Interfaces:**
- Consumes: backend `stop(reset_run_id=...)` (Task 5).
- Produces: `self.reset_run_id_on_stop` CheckboxGroup; `callback_stop_orch` calls `backend.stop(reset_run_id=<checkbox state>)`; button label "Clear plan".

- [ ] **Step 1: Write the failing tests**

In `helao/framework/tests/test_app_operator.py`: ensure the `_MockBackend` records stop calls. Add to `_MockBackend.__init__` (alongside the other recording attrs ~line 63-68) `self.stop_calls = []`, and add the method:

```python
    async def stop(self, reset_run_id: bool = False):
        self.stop_calls.append(reset_run_id)
```

Then add the tests (use the existing `_FakeVisOp(Document())` + `_drain_callbacks(doc)` pattern):

```python
def test_clear_button_renamed_to_clear_plan():
    from bokeh.document import Document
    from helao.framework.app.operator.bokeh_operator import BokehOperator
    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    assert op.button_clear_expplan.label == "Clear plan"


def test_reset_checkbox_unchecked_by_default():
    from bokeh.document import Document
    from helao.framework.app.operator.bokeh_operator import BokehOperator
    op = BokehOperator(_FakeVisOp(Document()), _MockBackend())
    assert op.reset_run_id_on_stop.active == []


def test_stop_callback_forwards_checkbox_state():
    from bokeh.document import Document
    from helao.framework.app.operator.bokeh_operator import BokehOperator
    vis = _FakeVisOp(Document())
    be = _MockBackend()
    op = BokehOperator(vis, be)
    op.reset_run_id_on_stop.active = [0]          # check the box
    op.callback_stop_orch(None)
    _drain_callbacks(vis.doc)
    assert be.stop_calls and be.stop_calls[-1] is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_operator.py -k "clear_plan or reset_checkbox or stop_callback_forwards" -v`
Expected: FAIL — `reset_run_id_on_stop` attribute missing; label is still "Clear expplan".

- [ ] **Step 3: Add the checkbox**

In `bokeh_operator.py`, immediately after the `self.button_stop_orch = self._make_button("Stop Orch", ...)` definition (~line 471-473), add:

```python
        self.reset_run_id_on_stop = CheckboxGroup(labels=["reset run_id"], active=[])
```

(`CheckboxGroup` is already imported, line 46.)

- [ ] **Step 4: Rename the Clear button label**

Change its definition (~line 480-481):

```python
        self.button_clear_expplan = self._make_button(
            "Clear plan", "default", 100, self.callback_clear_expplan
        )
```

(Keep the attribute name `button_clear_expplan` and `callback_clear_expplan` unchanged.)

- [ ] **Step 5: Forward the checkbox state in `callback_stop_orch`**

Replace the body of `callback_stop_orch`:

```python
    def callback_stop_orch(self, event):
        LOGGER.info("stopping operator orch")
        reset = 0 in self.reset_run_id_on_stop.active
        self.vis.doc.add_next_tick_callback(partial(self.backend.stop, reset_run_id=reset))
        self.vis.doc.add_next_tick_callback(partial(self.update_tables))
```

- [ ] **Step 6: Relocate Clear + place the checkbox in the control row**

In the control-row layout (~774-779), change the row so `button_clear_expplan` sits right of `button_prepend_plan`, and the checkbox right of `button_stop_orch`:

```python
                        row(
                            self.button_add_expplan,
                            self.button_add_smpseqs,
                            self.button_prepend_plan,
                            self.button_clear_expplan,
                            self.button_start_orch,
                            self.button_stop_orch,
                            self.reset_run_id_on_stop,
                            spacing=4,
                            sizing_mode="stretch_width",
                        ),
```

- [ ] **Step 7: Run to verify pass**

Run: `conda run -n helao python -m pytest helao/framework/tests/test_app_operator.py -v`
Expected: PASS (whole file).

- [ ] **Step 8: Commit**

```bash
git add helao/framework/app/operator/bokeh_operator.py helao/framework/tests/test_app_operator.py
git commit -m "feat(framework): operator reset-run_id checkbox + relocate/rename Clear plan"
```

---

### Task 7: full-suite regression check

**Files:** none (verification only).

- [ ] **Step 1: Run the full framework suite**

Run: `conda run -n helao python -m pytest helao/framework/tests -p no:warnings`
Expected: PASS — prior baseline 1656 passed, 28 skipped; now **1670 passed, 28 skipped** (+14 new tests: 2 model, 3 sequence_order, 3 apply_intent, 2 orch_api, 1 backend, 3 operator). Exact count may differ by ±a few; the requirement is zero failures.

- [ ] **Step 2: If any pre-existing test asserts an exact `SequenceModel.model_dump()` / round-trip equality**

Update that assertion to include `sequence_order`, commit with `test(framework): account for sequence_order in model dump assertions`. Otherwise no commit needed (Tasks 1-6 already committed).

---

## Self-Review

**Spec coverage:**
- A `sequence_order` field → Task 1 ✓; counter + stamping (0 / increment / reset) → Task 2 ✓.
- B `reset_run_id`: domain `apply_intent` → Task 3 ✓; orch endpoint + `_intent` → Task 4 ✓; backend port+adapter → Task 5 ✓.
- C operator checkbox + callback → Task 6 ✓; Clear relocate + rename → Task 6 ✓.
- Out-of-scope (history tabs, queue mgmt, estop/complete_idle, `seq.run_id` producer) → absent from all tasks ✓.
- Testing items from spec → Tasks 1-6 each carry the matching tests ✓.

**Placeholder scan:** none — every code step shows complete code; the two "if the existing shape differs" notes (Task 4 route return, Task 5 backend construction) are explicit fallbacks, not deferrals.

**Type consistency:** `reset_run_id: bool = False` identical across `apply_intent` (T3), `OrchDriver.stop`/`_intent`/routes (T4), backend port+adapter (T5), operator callback bool (T6). `active_run_seq_counter: int` defined T2, used T2. `sequence_order: Optional[int]` defined T1, stamped T2. `button_clear_expplan` attribute name preserved while label changes (T6).
