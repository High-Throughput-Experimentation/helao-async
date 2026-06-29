# Spec 1: run_id grouping (`sequence_order`) + stop-without-reset control

**Date:** 2026-06-29
**Scope:** framework only (`helao/framework/`)
**Sibling:** Spec 2 (operator queue management — history-tab reorder + experiment/action queue reorder/remove) is separate and out of scope here.

## Problem

1. Sequences have no analog to `action_order`/`experiment_order` — no field recording a sequence's dispatch position within its `run_id` grouping.
2. A normal Stop Orch leaves `active_run_id` intact, so the next sequence continues the same run grouping. There is no way to stop and deliberately *end* the current run grouping (so the next sequence starts a fresh `run_id`, restarting `sequence_order` at 0).

## Goal

- Add `sequence_order` to `SequenceModel`: the 0-indexed dispatch position of a sequence within its current `run_id` grouping.
- Add an **opt-in** ability to reset `active_run_id` on stop. Default behavior is unchanged (stop does NOT reset `run_id`). Expose it through the orchestrator `stop` endpoint and a BokehOperator checkbox.
- Two unrelated-but-bundled operator control tweaks: relocate and rename the "Clear expplan" button.

## Background (current behavior, verified)

- `active_run_id` is written only in `dispatch_sequence` (orchestration.py 1125-1128) and reset to `None` only by **estop** (line 705). Derivation: explicit `seq.run_id` wins; else if `active_run_id is None` seed from `seq.sequence_uuid`; else keep the prior value.
- Nothing in the framework assigns `seq.run_id`; it flows downward (`exp.run_id`/`action.run_id = active_run_id`). So a run_id grouping = all sequences dispatched from one start until a stop-with-reset or estop. Interleaved run_ids cannot occur.
- Normal stop: `apply_intent("stop")` (orchestration.py 683) sets `loop_intent = stop` only; it does NOT touch `active_run_id`. `complete_idle` (natural drain) does not either.

## Design

### Part A — `sequence_order`

**Model** — `helao/framework/models/sequence.py`, on the full `SequenceModel` (not `ShortSequenceModel`), mirroring `ExperimentModel.experiment_order`:

```python
sequence_order: Optional[int] = 0
```

**Counter** — `helao/framework/domain/orchestration.py`, on `OrchState`:

```python
active_run_seq_counter: int = 0
```

**Stamping** — in `dispatch_sequence`, capture the prior run id *before* the existing run_id-derivation block, then after it set the counter and stamp:

```python
prior_run_id = state.active_run_id
# ... existing run_id derivation (lines ~1125-1128) unchanged ...
if state.active_run_id == prior_run_id:
    state.active_run_seq_counter += 1
else:
    state.active_run_seq_counter = 0
seq.sequence_order = state.active_run_seq_counter
```

Semantics: first sequence of a run → prior `None` ≠ new value → `0`. Consecutive sequences in the same run → equal → increment. A new `run_id` (including the first sequence after a stop-with-reset or estop drops `active_run_id` to `None`) → `0`.

### Part B — stop without resetting run_id (opt-in to reset)

**Domain** — `apply_intent` gains a keyword:

```python
def apply_intent(state, intent, *, reason: str = "", reset_run_id: bool = False):
```

In the `("stop", "intend_stop")` branch, after setting `loop_intent`:

```python
if reset_run_id:
    state.active_run_id = None
```

Default `False` ⇒ current behavior exactly. Only the stop branch consults it.

**App** — `helao/framework/app/orch_api.py`:
- `_intent(self, intent, *, reason="", reset_run_id=False)` forwards `reset_run_id` to `apply_intent`.
- `stop(self, reset_run_id: bool = False)` (the orchestrator endpoint) → `await self._intent("stop", reset_run_id=reset_run_id)`. `reset_run_id` is a FastAPI query param (bool, default False).

**Backend** — `helao/framework/ports/operator_backend.py` and `adapters/operator_backend.py`:
- Port: `async def stop(self, reset_run_id: bool = False) -> None: ...`
- Adapter: `async def stop(self, reset_run_id: bool = False): await self._call("stop", params_dict={"reset_run_id": reset_run_id})`

### Part C — operator UI (`helao/framework/app/operator/bokeh_operator.py`)

1. **Reset-run_id checkbox.** Add (near the Stop Orch button definition, ~line 471) an unchecked CheckboxGroup (`CheckboxGroup` already imported, line 46):

   ```python
   self.reset_run_id_on_stop = CheckboxGroup(labels=["reset run_id"], active=[])
   ```

   Place it in the control row immediately to the right of `button_stop_orch`.

2. **Stop callback passes the flag.** In `callback_stop_orch`:

   ```python
   reset = 0 in self.reset_run_id_on_stop.active
   self.vis.doc.add_next_tick_callback(partial(self.backend.stop, reset_run_id=reset))
   self.vis.doc.add_next_tick_callback(partial(self.update_tables))
   ```

3. **Relocate + rename the Clear button.** Rename the button label `"Clear expplan"` → `"Clear plan"` (definition ~line 481; `callback_clear_expplan` / attribute name `button_clear_expplan` unchanged). In the control-row layout (currently: `button_add_expplan, button_add_smpseqs, button_prepend_plan, button_start_orch, button_stop_orch, button_clear_expplan` ~lines 774-779), move `button_clear_expplan` to sit immediately right of `button_prepend_plan`. New order:

   `add_expplan, add_smpseqs, prepend_plan, clear_expplan("Clear plan"), start_orch, stop_orch, reset_run_id_on_stop`

## Out of scope

- History-tab reorder and experiment/action queue reorder/remove (Spec 2).
- Any change to estop's existing `active_run_id` reset, or to `complete_idle`.
- Assigning `seq.run_id` anywhere (no producer is added).

## Testing

- **Model:** `SequenceModel().sequence_order == 0`; round-trips through `model_dump()`.
- **`sequence_order` stamping (dispatch_sequence):** first sequence of a run → 0; two consecutive sequences (same run, no explicit run_id) → 0 then 1; after a stop-with-reset (`active_run_id` `None`) the next sequence → 0.
- **`apply_intent` reset_run_id:** `apply_intent(state, "stop")` leaves `active_run_id` unchanged; `apply_intent(state, "stop", reset_run_id=True)` sets it to `None`; estop branch unchanged.
- **orch_api `stop`:** calling `stop(reset_run_id=True)` drops `active_run_id`; `stop()` (default) leaves it; `_intent` forwards the flag.
- **Backend adapter:** `stop(reset_run_id=True)` issues a `_call("stop", params_dict={"reset_run_id": True})`.
- **Operator:** checkbox default unchecked; `callback_stop_orch` calls `backend.stop` with `reset_run_id` matching the checkbox; the Clear button label reads "Clear plan" and sits immediately right of Prepend plan in the control row.

## Risks

- Low. `sequence_order` is additive with a safe default and reuses existing run_id derivation. `reset_run_id` defaults to the current behavior, so existing stop callers are unaffected. The operator changes are layout/label plus one new optional control.
