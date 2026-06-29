# Spec: `experiment_order` on `ExperimentModel`

**Date:** 2026-06-29
**Scope:** framework only (`helao/framework/`)

## Problem

`ActionModel` carries `action_order` (the action's index within its experiment), but
there is no analog on `ExperimentModel` for an experiment's index within its sequence.
Downstream consumers cannot order experiments within a sequence from the model alone.

## Goal

Add `experiment_order` to `ExperimentModel` as the integer index of an experiment among
the list of experiments in its enclosing sequence — the direct analog of
`action_order`.

This spec covers **only** the `experiment_order` field addition and its stamping. It does
**not** introduce minimal/abbreviated child models, change the `dispatched_*`/`planned_*`
list shapes, or alter what gets written to the `.yml` files.

## Design

### Model field

`helao/framework/models/experiment.py` — add to `ExperimentModel` (the full model, not
`ShortExperimentModel`, mirroring `action_order` which lives on `ActionModel` not
`ShortActionModel`):

```python
experiment_order: Optional[int] = 0
```

Default `0`, `Optional[int]`, byte-for-byte matching `ActionModel.action_order`
(`helao/framework/models/action.py:133`). Add a matching attribute line to the class
docstring. `RunExperiment(ExperimentModel)` inherits the field automatically — no change
to `run_models.py`.

### Stamping

`experiment_order` is stamped at dispatch, the analog of how `action_order` is assigned at
action dispatch. The orchestrator already maintains the right counter:

- `OrchState.active_seq_exp_counter` (`orchestration.py:188`, default `0`)
- reset to `0` per sequence in `dispatch_sequence()` (`orchestration.py:1142`)
- incremented per experiment in `dispatch_experiment()` (`orchestration.py:1239`)

So the counter's value **immediately before** the `+= 1` at line 1239 is the 0-indexed
position of the experiment within its sequence. In `dispatch_experiment()`, stamp:

```python
exp.experiment_order = state.active_seq_exp_counter
state.active_seq_exp_counter += 1
```

(insert the assignment on the line directly above the existing increment at 1239). This
makes `experiment_order` 0-indexed and per-sequence, consistent with the counter's
existing reset semantics.

### Out of scope

- No new minimal models (`DispatchedActionModel` / `DispatchedExperimentModel`).
- No retyping of `dispatched_actions_abbr` / `dispatched_experiments_abbr`.
- No change to `planned_*` lists, serialization, or `.yml` write contents.
- `ShortExperimentModel`, `ProcessModel`, and the full→short inheritance untouched.

## Testing

- **Model:** `ExperimentModel().experiment_order == 0`; round-trips through
  `as_dict()` / construction; `RunExperiment` inherits it.
- **Stamping:** dispatching N experiments in one sequence stamps `experiment_order`
  `0..N-1` in order; the counter reset in `dispatch_sequence()` means a second sequence
  restarts at `0`.

## Risks

Minimal. Additive field with a safe default; no consumer currently reads
`experiment_order`, and the stamping reuses an existing, already-correct counter.
