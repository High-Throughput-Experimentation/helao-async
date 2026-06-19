# Operator UI follow-ups — design

**Date:** 2026-06-19
**Branch:** `feat/standalone-operator`
**Status:** approved for planning
**Builds on:** `2026-06-19-plan-buffer-sequences-design.md` (plan buffer already implemented)

## Problem

Five follow-up UI changes to `BokehOperator` (`helao/core/servers/operator/bokeh_operator.py`) plus supporting orch/backend changes:

- **A. Param type-hint rendering.** Show each sequence/experiment parameter as a single label above its input: the parameter name in normal weight followed by the type hint in italics inside square brackets (e.g. `solid_plate_id [int]`). Today the name is the Bokeh input's `title` (rendered above the input) and the type is a separate plain `Div` beside the input.
- **B. Sequence-label sanitization.** Disallow spaces and double underscores in sequence labels: replace any run of whitespace/underscores with a single underscore, both as the operator label field is edited and in `orch.py` so labels arriving from outside the operator are corrected too.
- **C. Save/restore label & campaign.** When "save seq/exp params" is enabled, persist the current sequence label, campaign name, and campaign uuid (one global most-recent set) alongside the saved params. "Load last seq/exp params" restores them into the label/campaign fields.
- **D. Row reorder/remove controls.** Add up / down / remove controls beside the plan table and the orchestrator sequence-queue table. The plan table becomes one-row-per-sequence. Orch-queue controls are enabled only when the loop is stopped; plan-table controls are always enabled.
- **E. UUID truncation.** Show only the last 8 characters of any uuid value in the history and queue tables (the queue tables and the history `campaign_uuid` currently show full uuids).

## Decisions (locked)

- A: merge name + italic-bracketed type into one label **above** the input (name not italic).
- B: sanitizer is `re.sub(r"[\s_]+", "_", label)` — collapses any whitespace/underscore run to a single underscore; preserves intentional single underscores.
- C: single global most-recent label/campaign (not per-named-entry).
- D: plan table changes to **one row per sequence**; reorder/remove map 1:1 to rows. Orch-queue controls gated on `loop_state == stopped`; plan controls always enabled.
- E: truncate every column whose key ends in `_uuid` to its last 8 characters in the history and queue tables.

## Non-goals / unchanged

- The seqspec enqueue path and the plan-buffer flush semantics from the prior spec are unchanged.
- No change to how sequences are stored on disk or to the orch run loop.
- Reordering does not change run_id semantics.

## Design

### A. Merged name + italic type label

The input's `title` is load-bearing in three ways: it is the **parameter key** when building the params dict (`{paraminput.title: value}` at four sites), the match key in `find_input`, and the `x_mm`/`y_mm` lookup in `update_xysamples`. To render a custom merged label we decouple the *display* from the *key* by moving the key onto each widget's Bokeh `name` property (every Bokeh model has a free-form `name: str | None` that does not affect rendering).

In `add_dynamic_inputs`:
- Create each parameter `TextInput` with `title=None` and `name=args[idx]` (was `title=args[idx]`). For the `solid_custom_position` / `liquid_custom_position` `Select` widgets, likewise set `name=args[idx]` (keep their existing construction otherwise).
- For the special private inputs (`elements`, `code`, `composition`, and the disabled `x_mm`/`y_mm`/`solid_sample_no` helpers) set `.name` to the same identifier their `title` currently holds (these keep their visible `title` — they are display labels, not type-hinted params).
- Build the type string with the existing expression:
  `str(argtypes[idx]).split()[-1].strip("'<>]").split(".")[-1].replace("[", " of ")`.
- Render the merged label as a `Div` placed **above** the input in the cell:
  `Div(text=f"{args[idx]} <i>[{typestr}]</i>", ...)`.
  Replace the current `[ [input, Div(type)], Spacer ]` cell layout with `[ [label_div], [input], Spacer ]`. Remove the old separate type `Div`.

Replace `.title` with `.name` at the param-key sites and lookups:
- params-dict comprehensions in `callback_enqueue_seqspec` (~1256), `callback_to_seqtab` (~1286), `populate_sequence` (~1543), `populate_experimentmodel` (~1575): change `paraminput.title` → `paraminput.name`.
- `update_xysamples` (~1912/1914): `paraminput.title == "x_mm"/"y_mm"` → `paraminput.name == ...`.
- `find_input` (~2008): match `inp.name == name` (instead of `inp.title == name`).
- `callback_to_seqtab` sets `self.seq_param_input[i].value` after matching `x.title in loaded_params` (~1298): change to `x.name in loaded_params`.

`get_last_seq_pars` / `get_last_exp_pars` use `find_input`, so they follow automatically.

> Note: the plate-map branches (`solid_plate_id` etc.) run only when `dataAPI` is configured (HTE). The `.title`→`.name` substitution is faithful (same identifier string), but those branches are not exercised by the Linux test env; flag for an HTE smoke check.

### B. Label sanitization

Add a module-level helper in `helao/core/servers/orch.py` (add `import re`):

```python
def sanitize_sequence_label(label):
    """Collapse whitespace/underscore runs to single underscores (None-safe)."""
    if not label:
        return label
    return re.sub(r"[\s_]+", "_", label)
```

Apply it on every path where a sequence enters the queue, by sanitizing inside `_prep_sequence_meta` (covers `add_sequence` and `prepend_sequences`) and once per sub-sequence in `add_split_sequences`:

```python
    def _prep_sequence_meta(self, sequence):
        ...
        sequence.sequence_label = sanitize_sequence_label(sequence.sequence_label)
```
In `add_split_sequences`, after copying each `sub_sequence`, set `sub_sequence.sequence_label = sanitize_sequence_label(sub_sequence.sequence_label)` (the split fallback delegates to `add_sequence`, which already sanitizes).

Operator side (`bokeh_operator.py`, add `import re` or reuse a small local helper): add an `on_change` handler to `input_sequence_label` and `input_sequence_label2` that rewrites the value when the sanitized form differs:

```python
    def _sanitize_label_callback(self, attr, old, new):
        cleaned = re.sub(r"[\s_]+", "_", new)
        if cleaned != new:
            self.vis.doc.add_next_tick_callback(
                partial(self.update_input_value, self._label_sender, cleaned)
            )
```
Concretely, wire one sanitizing callback per label input (binding the right sender). Sanitization is idempotent (a cleaned value cleans to itself), so the re-fired `on_change` terminates. The existing mirror callbacks keep `input_sequence_label`/`_label2` in sync.

### C. Save/restore global last-used label & campaign

`write_params(ptype, name, pars)` currently stores `pdict[ptype][name] = pars` when the matching "save" checkbox is active. Extend it to also persist a single global block when that checkbox is active:

```python
        pdict.setdefault("last_meta", {})
        pdict["last_meta"] = {
            "sequence_label": self.input_sequence_label.value,
            "campaign_name": self.input_campaign_name.value,
            "campaign_uuid": self.input_campaign_uuid.value,
        }
```
(written in the same `if save-active` branch, before `json.dump`). The default dict in the "file missing" branch becomes `{"seq": {}, "exp": {}, "last_meta": {}}`.

`get_last_seq_pars` / `get_last_exp_pars`: after restoring the param inputs, also restore the label/campaign fields from `pdict["last_meta"]` (read via a small `read_meta()` helper, or extend `read_params`). For each of `input_sequence_label`, `input_campaign_name`, `input_campaign_uuid`, schedule `update_input_value` with the stored value when present. (Setting `input_sequence_label` flows through the mirror + sanitizer.)

### D. Row reorder / remove controls

**Plan table → one row per sequence.** Change `experiment_plan_lists` keys from
`["sequence_name", "sequence_label", "experiment_name"]` to
`["sequence_name", "sequence_label", "num_experiments"]`.
In `update_tables`, build one row per buffered sequence:
```python
        for key in self.experiment_plan_lists:
            self.experiment_plan_lists[key] = []
        for seq in self.plan:
            self.experiment_plan_lists["sequence_name"].append(seq.sequence_name)
            self.experiment_plan_lists["sequence_label"].append(seq.sequence_label)
            self.experiment_plan_lists["num_experiments"].append(len(seq.planned_experiments))
        self.experiment_plan_source.data = self.experiment_plan_lists
        self.button_add_expplan.label = f"Add plan [{len(self.plan)}]"
```
(`seq_count` is now just `len(self.plan)`.) Update the Task-5 test `test_plan_table_rows` to assert `num_experiments == [1]` and that `sequence_name`/`sequence_label` are present.

**Plan-table controls (local buffer, always enabled).** Three buttons (`Plan ↑`, `Plan ↓`, `Plan ✕`) wired to callbacks that read `self.experiment_plan_source.selected.indices`:
```python
    def _selected_plan_idx(self):
        idxs = list(self.experiment_plan_source.selected.indices)
        return idxs[0] if idxs else None

    def callback_plan_move_up(self, event):
        i = self._selected_plan_idx()
        if i is not None and i > 0:
            self.plan[i - 1], self.plan[i] = self.plan[i], self.plan[i - 1]
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_plan_move_down(self, event):
        i = self._selected_plan_idx()
        if i is not None and i < len(self.plan) - 1:
            self.plan[i + 1], self.plan[i] = self.plan[i], self.plan[i + 1]
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))

    def callback_plan_remove(self, event):
        i = self._selected_plan_idx()
        if i is not None and 0 <= i < len(self.plan):
            del self.plan[i]
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))
```

**Orch sequence-queue controls (gated on stopped).** The sequence-queue table (`sequence_source`/`sequence_table`) is already one row per sequence. Three buttons (`Queue ↑`, `Queue ↓`, `Queue ✕`) read `self.sequence_source.selected.indices` and dispatch to the backend:
```python
    def callback_seq_move_up(self, event):
        idxs = list(self.sequence_source.selected.indices)
        if idxs and idxs[0] > 0:
            i = idxs[0]
            self.vis.doc.add_next_tick_callback(partial(self.backend.move_sequence, i, i - 1))
            self.vis.doc.add_next_tick_callback(partial(self.update_tables))
    # move_down: i < n_sequences-1 -> move_sequence(i, i+1)
    # remove: remove_sequence(i)
```
These three buttons get `disabled` toggled in `update_tables` alongside `button_prepend_plan`:
`disabled = loop_state != LoopStatus.stopped.value`.

**Backend** (`orch_backend.py`): add to `OrchBackend` ABC and both impls:
```python
    # ABC
    @abstractmethod
    async def move_sequence(self, from_idx: int, to_idx: int) -> None: ...
    @abstractmethod
    async def remove_sequence(self, idx: int) -> None: ...
    # LocalBackend
    async def move_sequence(self, from_idx, to_idx):
        await self.orch.move_sequence(from_idx, to_idx)
    async def remove_sequence(self, idx):
        await self.orch.remove_sequence(idx)
    # RemoteBackend
    async def move_sequence(self, from_idx, to_idx):
        await self._call("move_sequence", params_dict={"from_idx": from_idx, "to_idx": to_idx})
    async def remove_sequence(self, idx):
        await self._call("remove_sequence", params_dict={"idx": idx})
```

**Orch** (`orch.py`): mutate `sequence_dq` (a `zdeque`) by materializing, editing, and rebuilding:
```python
    def _rebuild_sequence_dq(self, seqs):
        self.sequence_dq.clear()
        for s in seqs:
            self.sequence_dq.append(s)

    async def move_sequence(self, from_idx, to_idx):
        seqs = list(self.sequence_dq)
        n = len(seqs)
        if 0 <= from_idx < n and 0 <= to_idx < n:
            seq = seqs.pop(from_idx)
            seqs.insert(to_idx, seq)
            self._rebuild_sequence_dq(seqs)

    async def remove_sequence(self, idx):
        seqs = list(self.sequence_dq)
        if 0 <= idx < len(seqs):
            seqs.pop(idx)
            self._rebuild_sequence_dq(seqs)
```
(Iterating a `zdeque` yields decompressed copies; rebuilding re-compresses. Sequences keep their pickled uuid/run_id. No effect on `active_run_id` or the active sequence, which is already popped off the dq.)

**OrchAPI** (`orch_api.py`): two endpoints mirroring the existing param-style routes:
```python
        @self.post("/move_sequence", tags=["private"])
        async def move_sequence(from_idx: int, to_idx: int):
            await self.orch.move_sequence(from_idx, to_idx)
            return {"n_sequences": len(self.orch.sequence_dq)}

        @self.post("/remove_sequence", tags=["private"])
        async def remove_sequence(idx: int):
            await self.orch.remove_sequence(idx)
            return {"n_sequences": len(self.orch.sequence_dq)}
```

**Layout.** Place the plan-table controls in a small row under the `planhistory_tabs` block and the queue controls under the `queue_tabs` block in `layout4`. Use `_make_button`.

### E. UUID truncation

In `get_sequences`, `get_experiments`, `get_actions`, truncate any column whose key ends in `_uuid`:
```python
        for key in self.sequence_lists:
            vals = [r.get(key) for r in rows]
            if key.endswith("_uuid"):
                vals = [str(v)[-8:] if v else v for v in vals]
            self.sequence_lists[key] = vals
        self.sequence_source.data = self.sequence_lists
```
(same pattern for experiments/actions). In `get_history`, the seq/exp/action uuids are already truncated; additionally truncate `campaign_uuid` if/when it is added to a history list (the current history lists do not include campaign_uuid, so no change needed there unless present — apply `str(v)[-8:]` wherever a `*_uuid` is appended to a history list that isn't already truncated).

## Data flow (D)

```
plan table row select --Plan ↑/↓/✕--> reorder/del self.plan[i] --> update_tables
queue table row select --Queue ↑/↓/✕ (only if stopped)--> backend.move_sequence/remove_sequence(i)
        Local --> orch.move_sequence/remove_sequence --> rebuild sequence_dq
        Remote --> POST /move_sequence|/remove_sequence --> orch.* --> rebuild sequence_dq
--> update_tables
```

## Error handling

- All selection callbacks no-op when nothing is selected or the move is out of range (guards shown above).
- `move_sequence` / `remove_sequence` clamp to valid indices and no-op otherwise (return current count).
- Sanitizer is None-safe and idempotent.
- `read` of `last_meta` tolerates a missing key (older `previous_params.json`) by defaulting to `{}`.

## Testing (extend `helao/core/tests/test_standalone_operator.py`, same assert-style)

1. **A — param key via `.name`:** construct operator, select `seq0` (its lib fn has a param), `populate_sequence`; assert `op.plan[0].sequence_params` is keyed by the param name (proves `.name` is used, not `.title`). Assert the param input has `title is None` and `name == "<param>"`.
2. **A — find_input by name:** add an input with `name="solid_sample_no"`, assert `find_input(inputs, "solid_sample_no")` returns it.
3. **B — sanitizer:** `sanitize_sequence_label("a b__c d")` == `"a_b_c_d"`; single underscore preserved (`"a_b"`→`"a_b"`); None→None.
4. **B — orch applies it:** add a sequence with label `"x y__z"` via `add_sequence` (Orch.__new__ harness), assert the enqueued sequence's `sequence_label == "x_y_z"`.
5. **B — operator field:** set `op.input_sequence_label.value = "a b"`, run the doc's queued callbacks (or call the sanitize callback directly), assert it becomes `"a_b"`.
6. **C — save/restore:** enable save checkbox, set label/campaign fields, `write_params("seq", "seq0", {...})`; clear the fields; `get_last_seq_pars()`; assert label/campaign restored.
7. **D — plan table one-row-per-seq:** buffer two sequences (one manual 1-exp, one multi-exp); `update_tables`; assert `experiment_plan_source.data["num_experiments"]` has one entry per sequence and `sequence_name` length == len(plan); `Add plan [2]`.
8. **D — plan reorder/remove:** buffer [A,B,C]; set `experiment_plan_source.selected.indices=[2]`; `callback_plan_move_up`; assert order [A,C,B]; select+remove; assert removal.
9. **D — orch move/remove:** `Orch.__new__` harness with three sequences in `sequence_dq`; `move_sequence(2,0)` → front order; `remove_sequence(0)` → removed; counts correct.
10. **D — backend delegation:** Local forwards to `orch.move_sequence/remove_sequence`; Remote posts to `move_sequence`/`remove_sequence` with `params_dict` indices.
11. **D — queue button gate:** `button_seq_move_up/down/remove` `.disabled` True when loop started, False when stopped.
12. **E — uuid truncation:** `_MockBackend.list_sequences` returns a row with a long `sequence_uuid`/`campaign_uuid`; `get_sequences`; assert the table shows only the last 8 chars; same for experiments (`experiment_uuid`) and actions (`action_uuid`).

Run via `python -m helao.core.tests.test_standalone_operator` and `python run_unit_tests.py`.

## Affected files

- `helao/core/servers/operator/bokeh_operator.py` — A (merged label + `.name` decoupling), B (label callback), C (write/read meta + restore), D (plan table one-row-per-seq, reorder/remove callbacks + buttons + layout + gate), E (uuid truncation in queue getters).
- `helao/core/servers/orch.py` — B (`sanitize_sequence_label`, applied in `_prep_sequence_meta` + split), D (`move_sequence`, `remove_sequence`, `_rebuild_sequence_dq`), `import re`.
- `helao/core/servers/operator/orch_backend.py` — D (`move_sequence`/`remove_sequence` on ABC + Local + Remote).
- `helao/core/servers/orch_api.py` — D (`/move_sequence`, `/remove_sequence` endpoints).
- `helao/core/tests/test_standalone_operator.py` — tests above; update `test_plan_table_rows` for the new plan-table columns.
