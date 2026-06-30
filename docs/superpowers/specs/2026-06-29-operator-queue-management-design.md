# Spec 2: operator queue management (history-tab order + experiment/action queue edits)

**Date:** 2026-06-29
**Scope:** framework only (`helao/framework/`)
**Sibling:** Spec 1 (run_id grouping + stop control) is merged and out of scope here.

## Problem

1. The operator's history-tab group reads Action / Experiment / Sequence left-to-right; the desired reading order is Sequence → Experiment → Action.
2. The operator lets the user reorder/remove **sequence** queue items only when the orchestrator is stopped. There is no equivalent for the **experiment** and **action** queues, which is needed when hand-driving a manually-built sequence.

## Goal

- **D:** Reorder the history tabs so the group is `Planner, Sequence History, Experiment History, Action History`.
- **E:** Allow experiment-queue and action-queue reorder + removal in the operator, enabled only when the orchestrator is **stopped AND the active sequence is manual**. Add the full stack (domain queue mutators → orch endpoints → backend methods → operator buttons/callbacks/gating), and make operator-built manual sequences actually carry `manual_action=True`.

## Background (verified)

- `move_sequence`/`remove_sequence` already exist end-to-end and are the mirror template: domain `orchestration.py:503/513`, orch routes `orch_api.py:1551/1556`, backend `ports/operator_backend.py:69/72` + `adapters/operator_backend.py:149/154`, operator `button_seq_*` (`bokeh_operator.py:462-469`) with `callback_seq_move_up/down/remove` reading `self.sequence_source.selected.indices`.
- Sequence-queue buttons are gated stopped-only at `bokeh_operator.py:2635-2639` (`queue_disabled = loop_state != stopped`).
- `get_orch_state` (`orch_api.py:1486`) already returns `active_sequence` as a full dict (so `manual_action` is available to the operator with no new payload field) — but the operator's manual-wrap (`append_experiment`/`prepend_experiment`, `bokeh_operator.py:1861-1876`) builds `Sequence(sequence_name="manual_orch_seq", …)` **without** setting `manual_action`, so the flag is never true today.
- No experiment/action queue buttons, callbacks, domain mutators, endpoints, or backend methods currently exist.

## Design

### D — history-tab order

`bokeh_operator.py` `planhistory_tabs` (~386-392): reorder its `tabs=[...]` to
`[self.planner_tab, self.sequence_history_tab, self.experiment_history_tab, self.action_history_tab]`
(Planner stays first; the three history tabs become Sequence, Experiment, Action). Tab titles and the TabPanel objects are unchanged — only list order.

### E — experiment/action queue reorder + removal

**Manual flag.** In `append_experiment` and `prepend_experiment` (`bokeh_operator.py`), set `manual_action=True` on the synthesized `Sequence(sequence_name="manual_orch_seq", …)`. This is the single source of "manual" — it flows through `get_active_sequence` into the `get_orch_state` payload.

**Domain mutators** (`orchestration.py`, mirroring `move_sequence`/`remove_sequence`):
- `move_experiment(state, from_idx, to_idx) -> OrchState` — pop/insert on `state.experiment_dq`; out-of-range no-op.
- `remove_experiment(state, idx) -> OrchState` — `del state.experiment_dq[idx]`; out-of-range no-op.
- `move_action(state, from_idx, to_idx) -> OrchState` — same on `state.action_dq`.
- `remove_action(state, idx) -> OrchState` — same on `state.action_dq`.

**Orch endpoints** (`orch_api.py`, mirroring the `/move_sequence` route): `/move_experiment`, `/remove_experiment`, `/move_action`, `/remove_action`. Each calls the matching domain mutator and returns `{"n_experiments": len(driver.state.experiment_dq)}` / `{"n_actions": len(driver.state.action_dq)}`.

**Backend** (port + adapter, mirroring `move_sequence`/`remove_sequence`):
- Port: `move_experiment(from_idx, to_idx)`, `remove_experiment(idx)`, `move_action(from_idx, to_idx)`, `remove_action(idx)`.
- Adapter: `_call("move_experiment", params_dict={"from_idx":…, "to_idx":…})` etc.; `_call("remove_experiment", params_dict={"idx":…})` etc.

**Operator buttons + callbacks** (`bokeh_operator.py`, mirroring `button_seq_*` / `callback_seq_*`):
- `button_exp_move_up`, `button_exp_move_down`, `button_exp_remove` with `callback_exp_move_up/down/remove` reading `self.experiment_source.selected.indices` and dispatching `backend.move_experiment`/`remove_experiment` (move_down bounds-checks against `len(self.experiment_source.data.get("experiment_name", []))`).
- `button_act_move_up`, `button_act_move_down`, `button_act_remove` with `callback_act_move_up/down/remove` reading `self.action_source.selected.indices` and dispatching `backend.move_action`/`remove_action` (move_down bounds-checks `len(self.action_source.data.get("action_name", []))`).
- Place the experiment-queue button row and action-queue button row in the Queues layout block alongside the existing sequence-queue button row.

**Gating** (`bokeh_operator.py`, the state-update method around 2635-2639): compute
`manual_seq = bool((state.get("active_sequence") or {}).get("manual_action"))`
and `exp_act_disabled = (loop_state != LoopStatus.stopped.value) or (not manual_seq)`. Apply `exp_act_disabled` to all six new buttons. The existing sequence-queue buttons keep their stopped-only gate (unchanged).

## Out of scope

- Spec 1 work (sequence_order, reset_run_id) — merged.
- Any change to how sequences are expanded/dispatched, or to `manual_action` semantics beyond setting it on operator-built manual sequences.
- Reordering/removing the active (already-dispatched) sequence/experiment/action — these mutate only the pending deques, exactly like `move_sequence`/`remove_sequence`.

## Testing

- **D:** `planhistory_tabs.tabs` titles read `["Planner", "Sequence History", "Experiment History", "Action History"]` in order.
- **Domain:** `move_experiment`/`remove_experiment` reorder/drop `experiment_dq` (incl. out-of-range no-op); `move_action`/`remove_action` likewise on `action_dq`.
- **Orch endpoints:** each mutator endpoint applies the change and returns the right count.
- **Backend adapter:** each method issues the expected `_call(endpoint, params_dict)` (mirroring the existing `move_sequence`/`remove_sequence` recording test).
- **Operator manual flag:** `append_experiment`/`prepend_experiment` produce a sequence with `manual_action is True`.
- **Operator gating:** with `loop_state=stopped` and a manual active sequence, the six exp/action buttons are enabled; if not stopped, or active sequence not manual, they are disabled. Sequence-queue buttons remain gated on stopped only.
- **Operator callbacks:** selecting an experiment/action row and invoking each callback dispatches the matching backend method with the right indices (mirroring the existing `callback_seq_*` tests).

## Risks

- Moderate but well-bounded: every piece mirrors the proven `move_sequence`/`remove_sequence` stack. Main new surface is the gating predicate and the manual-flag wiring; both are small and unit-tested. No change to dispatch/expansion logic.
