# Plan buffer of separate sequences — design

**Date:** 2026-06-19
**Branch:** `feat/standalone-operator`
**Status:** approved for planning

## Problem

`BokehOperator` builds the operator "plan" as a single mutable `Sequence`
(`self.sequence`). Selecting a library sequence unpacks it into experiments that
are appended/prepended into `self.sequence.planned_experiments`; selecting an
experiment appends/prepends that experiment into the same list. The plan is thus
a *custom sequence builder* that flattens many sources into one sequence.

We want the plan to instead be an **ordered buffer of independent `Sequence`
objects**. A lone experiment becomes its own "manual" sequence. The whole buffer
is concatenated onto the orchestrator's sequence queue on flush, or prepended to
the front of the queue when the orchestrator is paused. The plan is no longer
used to build a single custom sequence.

Separately, `Sequence.run_id` is currently generated inside
`Orch.add_sequence` / `Orch.add_split_sequences` (on add-to-empty-queue) and
overwritten at dequeue. We want run_id stamped onto each sequence as the plan is
added to the queue, while preserving the existing back-to-back grouping
semantics.

## Goals

1. Plan becomes `List[Sequence]` (ordered buffer of separate sequences); never
   merged into one custom sequence.
2. Append/prepend of a library *sequence* inserts a whole `Sequence` into the
   buffer (end / front).
3. Append/prepend of an *experiment* wraps it as one manual `Sequence`
   (`sequence_name="manual_orch_seq"`, one planned experiment) — **one manual
   sequence per experiment** — inserted into the buffer (end / front).
4. Per-sequence metadata (label / campaign name+uuid / comment) is captured at
   **buffer-insert** time, so different buffered sequences can carry different
   metadata.
5. Flush operations:
   - **Add plan**: enqueue every buffered sequence via `add_sequence`.
   - **Split plan**: enqueue every buffered sequence via `add_split_sequences`.
   - **Prepend plan** (new): insert the whole buffer at the front of the orch
     sequence queue preserving buffer order; enabled only when the orch loop is
     stopped (paused).
   - **Clear expplan**: discard the buffer.
6. `Sequence.run_id` is stamped at plan-add (orch-side), preserving back-to-back
   sharing: empty/just-cleared queue → fresh run_id; non-empty (in-flight) →
   reuse the active run_id. Clear (running or stopped) and natural drain both
   start a fresh run_id on the next plan-add.

## Non-goals / unchanged

- The seqspec enqueue path (`callback_enqueue_seqspec`) already enqueues
  directly to the orch and is untouched.
- Appending an experiment *into an existing buffered sequence* is not supported;
  each experiment is its own manual sequence (per decision).
- estop's `active_run_id = None` reset and the disk-restore run_id paths are
  unchanged.
- No client-side run_id generation; `RemoteBackend` inherits run_id stamping via
  the orch endpoints.

## Design

### Data model (`BokehOperator`)

Replace `self.sequence: Optional[Sequence]` with:

```python
self.plan: List[Sequence] = []
```

The `sequence: Sequence` class annotation and all `self.sequence` reads/writes
are migrated to `self.plan`.

### Metadata capture helper

```python
def _capture_metadata(self, seq: Sequence) -> None:
    """Stamp label / campaign / comment from the current inputs onto seq."""
    seq.sequence_label = self.input_sequence_label.value
    if self.input_sequence_comment.value != "":
        seq.sequence_comment = self.input_sequence_comment.value
    campaign_name = self.input_campaign_name.value
    if campaign_name != "":
        seq.campaign_name = campaign_name
        if self.input_campaign_uuid.value.strip() == "":
            seq.campaign_uuid = md5_string(campaign_name)
        else:
            seq.campaign_uuid = self.input_campaign_uuid.value.strip()
```

This reuses the body of the current `_apply_sequence_to_orch`, which is removed
(its dispatch responsibility moves to the flush callbacks).

### Buffer-insert operations

`populate_sequence(prepend)` — rewritten:

- unpack the selected library sequence into `expplan_list` via
  `self.backend.unpack_sequence(...)` (unchanged call),
- build a fresh `Sequence(sequence_name=selected, sequence_params=params,
  planned_experiments=expplan_list)`,
- `self._capture_metadata(seq)`,
- `self.plan.insert(0, seq)` if `prepend` else `self.plan.append(seq)`,
- keep the existing `write_params("seq", ...)` call.

`append_experiment` / `prepend_experiment` — rewritten to wrap one experiment:

- build the `Experiment` via `populate_experimentmodel()` (which keeps building
  the model + `write_params("exp", ...)` but **no longer touches a shared
  sequence**),
- wrap: `seq = Sequence(sequence_name="manual_orch_seq",
  planned_experiments=[experimentmodel])`,
- `self._capture_metadata(seq)`,
- insert at front (prepend) / end (append) of `self.plan`.

`populate_experimentmodel()` loses its `self.sequence` mutation block (the
`if self.sequence is None: ...; self.sequence.sequence_name = "manual_orch_seq"`
lines); it returns only the `Experiment`.

### Flush operations (`BokehOperator` callbacks)

```python
def callback_add_expplan(self, event):     # "Add plan"
    for seq in self.plan:
        self.vis.doc.add_next_tick_callback(partial(self.backend.add_sequence, seq))
    self.plan = []
    self.vis.doc.add_next_tick_callback(partial(self.update_tables))

def callback_add_split_sequences(self, event):   # "Split plan"
    for seq in self.plan:
        self.vis.doc.add_next_tick_callback(partial(self.backend.add_split_sequences, seq))
    self.plan = []
    self.vis.doc.add_next_tick_callback(partial(self.update_tables))

def callback_prepend_plan(self, event):     # NEW "Prepend plan"
    plan = self.plan
    self.plan = []
    self.vis.doc.add_next_tick_callback(partial(self.backend.prepend_sequences, plan))
    self.vis.doc.add_next_tick_callback(partial(self.update_tables))

def callback_clear_expplan(self, event):
    self.plan = []
    self.vis.doc.add_next_tick_callback(partial(self.update_tables))
```

Note: Add/Split iterate and dispatch per sequence (order preserved by append).
Prepend dispatches the *whole list* in one backend call so the front-insert
preserves buffer order (per-sequence prepend calls would reverse it).

### New "Prepend plan" button

- Created alongside the existing plan buttons:
  `self.button_prepend_plan = self._make_button("Prepend plan", "default", 100,
  self.callback_prepend_plan)`.
- Placed next to `button_add_expplan` / `button_add_smpseqs` in both button rows
  in `layout4`.
- Enable/disable set in `update_tables` from `loop_state`:
  `self.button_prepend_plan.disabled = (loop_state != LoopStatus.stopped.value)`.
  (Disabled while running; enabled when stopped/paused/idle.)

### Plan table (`update_tables`)

Iterate the buffer (outer) then each sequence's planned experiments (inner):

```python
for key in self.experiment_plan_lists:
    self.experiment_plan_lists[key] = []
seq_count = 0
for seq in self.plan:
    seq_count += 1
    for D in seq.planned_experiments:
        self.experiment_plan_lists["sequence_name"].append(seq.sequence_name)
        self.experiment_plan_lists["sequence_label"].append(seq.sequence_label)
        self.experiment_plan_lists["experiment_name"].append(D.experiment_name)
self.experiment_plan_source.data = self.experiment_plan_lists
...
self.button_add_expplan.label = f"Add plan [{seq_count}]"
```

The "Add plan [N]" counter shows **number of buffered sequences** (was
experiment count). Columns are unchanged.

### Backend (`orch_backend.py`)

Add to the `OrchBackend` ABC:

```python
@abstractmethod
async def prepend_sequences(self, sequences: list) -> object: ...
```

`LocalBackend`:

```python
async def prepend_sequences(self, sequences):
    return await self.orch.prepend_sequences(sequences=sequences)
```

`RemoteBackend`:

```python
async def prepend_sequences(self, sequences):
    return await self._call(
        "prepend_sequences",
        json_dict={"sequences": [s.model_dump() for s in sequences]},
    )
```

### Orchestrator (`orch.py`)

Add a run_id helper:

```python
def _ensure_run_id(self) -> UUID:
    """Return the run_id to stamp on a sequence being added.

    Empty/just-cleared queue -> fresh run_id; non-empty -> reuse the in-flight
    active_run_id (back-to-back sharing).
    """
    if len(self.sequence_dq) == 0:
        self.active_run_id = gen_uuid()
    return self.active_run_id
```

`add_sequence`: replace the `if len(self.sequence_dq) == 0: self.active_run_id =
gen_uuid()` block with `sequence.run_id = self._ensure_run_id()` (before
`self.sequence_dq.append(sequence)`).

`add_split_sequences`: capture `run_id = self._ensure_run_id()` once before the
sub-sequence enqueue loop; remove the inner `if len == 0: active_run_id =
gen_uuid()`; set `sub_sequence.run_id = run_id` for each sub-sequence before
append. (The no-split fallback delegates to `add_sequence`, which stamps on its
own.)

New `prepend_sequences`:

```python
async def prepend_sequences(self, sequences: List[Sequence]) -> List[UUID]:
    """Insert sequences at the front of the queue, preserving their order.

    Stamps uuid/codehash/run_id like add_sequence. Reuses the in-flight run_id
    if the queue is non-empty, else generates a fresh one.
    """
    run_id = self._ensure_run_id()
    uuids = []
    for i, sequence in enumerate(sequences):
        if sequence.sequence_uuid is None:
            sequence.sequence_uuid = gen_uuid()
        # populate codehash/codepath/funcname as in add_sequence
        ...
        sequence.run_id = run_id
        self.sequence_dq.insert(i, sequence)
        uuids.append(sequence.sequence_uuid)
    return uuids
```

The uuid/codehash population is identical to `add_sequence`; factor it into a
small `_prep_sequence_meta(sequence)` helper shared by `add_sequence` and
`prepend_sequences` to avoid duplication.

Dequeue change in `loop_task_dispatch_sequence` (~line 766-768): replace the
overwrite

```python
if self.active_run_id is not None:
    self.active_sequence.run_id = self.active_run_id
```

with derive-from-sequence:

```python
if self.active_sequence.run_id is not None:
    self.active_run_id = self.active_sequence.run_id
elif self.active_run_id is not None:
    self.active_sequence.run_id = self.active_run_id
```

Experiment (~935) and action (~1173) run_id attachment from `active_run_id` is
unchanged, so they inherit the active sequence's stamped run_id.

### OrchAPI (`orch_api.py`)

New endpoint mirroring `/append_sequence`:

```python
@self.post("/prepend_sequences", tags=["private"])
async def prepend_sequences(sequences: List[Sequence] = Body([], embed=True)):
    """Prepend a list of sequences to the front of the orch queue."""
    seqs = [s if isinstance(s, Sequence) else Sequence(**s) for s in sequences]
    uuids = await self.orch.prepend_sequences(sequences=seqs)
    return {"sequence_uuids": uuids}
```

## Data flow

```
select seq + params --append/prepend seq--> Sequence (unpacked) --_capture_metadata--> self.plan[ ]
select exp + params --append/prepend exp--> Sequence("manual_orch_seq",[exp]) --_capture_metadata--> self.plan[ ]

self.plan[ ] --Add plan----> backend.add_sequence(seq) per seq --------> orch.sequence_dq (append)  [run_id stamped]
self.plan[ ] --Split plan--> backend.add_split_sequences(seq) per seq --> orch.sequence_dq (append)  [run_id stamped]
self.plan[ ] --Prepend plan-> backend.prepend_sequences(plan) (1 call) -> orch.sequence_dq (insert front, ordered) [run_id stamped]
                              (enabled only when loop_state == stopped)
```

## Error handling

- Flush callbacks with an empty buffer dispatch nothing (loops over `[]`,
  `prepend_sequences([])` is a no-op returning `[]`). No special-casing needed.
- `prepend_sequences` on the orch with an empty list returns `[]` without
  touching `active_run_id` only if `_ensure_run_id` is called after the empty
  check — to avoid generating a stray run_id for an empty prepend, guard:
  `if not sequences: return []` at the top of `Orch.prepend_sequences`.
- Metadata capture on a manual sequence with blank campaign leaves
  campaign fields unset (same as today's behavior).

## Testing

Extend the existing operator test coverage
(`helao/core/tests/test_standalone_operator.py` and related) with:

1. **Buffer model**: append seq then append exp → `self.plan` has two
   `Sequence` objects; the manual one has `sequence_name == "manual_orch_seq"`
   and exactly one planned experiment.
2. **Order**: append A, prepend B, append C → buffer order `[B, A, C]`.
3. **Metadata capture**: set label/campaign inputs, append seq, change inputs,
   append second seq → each buffered sequence carries the inputs as they were at
   its insert.
4. **Flush add**: `callback_add_expplan` dispatches `add_sequence` once per
   buffered sequence and clears the buffer.
5. **Flush prepend**: `callback_prepend_plan` calls `backend.prepend_sequences`
   once with the full list and clears the buffer.
6. **Prepend enable gate**: `button_prepend_plan.disabled` is True when
   `loop_state` is started and False when stopped (drive via a fake orch state).
7. **Orch run_id sharing**: add seq to empty dq → run_id R1 stamped; add another
   while non-empty → same R1; `clear_sequences()` then add → new run_id R2.
8. **Orch prepend ordering + run_id**: `prepend_sequences([A,B,C])` onto a
   non-empty dq yields front order `A,B,C` and all carry the in-flight run_id.
9. **Dequeue derive**: a dequeued sequence with a stamped run_id sets
   `orch.active_run_id` to that value (experiments/actions inherit it).

Tests run via `python run_unit_tests.py` plus the standalone-operator test
module. No live hardware required (use the `test` deployment / fakes already
used by the operator tests).

## Affected files

- `helao/core/servers/operator/bokeh_operator.py` — plan buffer, insert/flush
  callbacks, prepend button, plan table, metadata helper.
- `helao/core/servers/operator/orch_backend.py` — `prepend_sequences` on ABC +
  Local + Remote.
- `helao/core/servers/orch.py` — `_ensure_run_id`, `_prep_sequence_meta`,
  `add_sequence` / `add_split_sequences` run_id stamping, `prepend_sequences`,
  dequeue derive.
- `helao/core/servers/orch_api.py` — `/prepend_sequences` endpoint.
- `helao/core/tests/test_standalone_operator.py` (+ any operator test helpers) —
  new cases above.
