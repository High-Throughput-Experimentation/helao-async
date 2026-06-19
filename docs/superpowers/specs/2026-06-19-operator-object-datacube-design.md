# Operator Object Datacube (HTML Tree) — Design

**Date:** 2026-06-19
**Branch:** `feat/standalone-operator`
**Component:** `helao/core/servers/operator/bokeh_operator.py`, `helao/core/servers/operator/orch_backend.py`

## Summary

Add two read-only hierarchical object views to the Bokeh operator, one beside each
existing tabbed table block. Selecting a row in the active tab renders the full
object as a collapsible HTML tree, with the object's `*_params` attribute expanded
and all other top-level attributes collapsed by default. A small header above each
tree shows the selected object's identity (name + truncated uuid; server name + port
for action servers).

The whole app widens to fill the browser window; each tabbed table and its tree split
50/50.

A second, independent feature prefixes each dynamically generated parameter input
label with its enumeration index (`"0) param name [type hint]"`).

## Background

Current operator structure (`bokeh_operator.py`):

- Two `Tabs` blocks stacked in a single fixed-width (`max_width = 1024`) column:
  - **`planhistory_tabs`** — *Plan*, *Action History*, *Experiment History*, *Sequence History* (the "non-queued" block).
  - **`queue_tabs`** — *Sequences*, *Experiments*, *Actions*, *Action Servers* (the orch queues).
- Each table is a `DataTable` over a `ColumnDataSource`; tables hold only a few display columns. Full objects fetched by the backend are discarded.
- Backend is abstracted (`OrchBackend` local, `RemoteBackend` over HTTP/OrchAPI). `list_sequences/experiments/actions` return **trimmed** dicts (`_SEQ_KEYS` etc.).
- Full objects already available locally for some rows:
  - **Plan** rows → `self.plan` (list of `Sequence` objects).
  - **History** rows → `get_histories()` returns full dicts.
  - **Action server** config → `self.vis.world_cfg["servers"][name]` (has `host`, `port`, `params`).
- Bokeh version: **3.9.0**.

Note: Bokeh's `DataCube` widget is a grouping/subtotal `DataTable` (fixed grouping
levels, per-level `collapsed`, numeric aggregators) — **not** a free-form key→value
tree, and cannot default-expand a single named attribute. A server-side HTML
`<details>` tree was chosen instead; it gives arbitrary depth and per-node collapse
with no JS/custom extension.

## Feature 1 — Object tree views

### 1.1 Tree renderer

`_object_to_html(obj, open_keys) -> str`

- Recursive HTML builder:
  - `dict` → `<details><summary>{key}</summary>{children}</details>` per item.
  - `list`/`tuple` → `<details><summary>{key} [{n}]</summary>{indexed children}</details>`.
  - scalar (`str`/`int`/`float`/`bool`/`None`) → leaf line `{key}: {value}`.
- Top-level nodes whose key is in `open_keys` render `<details open>`; all other
  top-level nodes and every nested node render closed.
- `open_keys` selection rule:
  - objects: any top-level key matching `*_params` (covers `sequence_params`,
    `experiment_params`, `action_params`).
  - action-server config: the `params` key.
- Pure server-side string; assigned to a `Div.text`. No JS, no custom Bokeh extension.
- Read-only (display only).

### 1.2 Tree header

A `Div` above each tree showing the selected object's identity:

- seq/exp/act/plan/history object → `"{name} · {uuid_last8}"`, using keys
  `{kind}_name` and `{kind}_uuid`. UUID truncated to last 8 chars (matches existing
  table convention).
- action server → `"{server_name} · {host}:{port}"` from `world_cfg["servers"][name]`.
- no selection → placeholder text (e.g. "select a row").

### 1.3 Data sourcing per tab

| Tab block | Tab | Object source |
|-----------|-----|---------------|
| planhistory | Plan | `self.plan[idx].as_dict()` (local) |
| planhistory | *History (3) | full dict retained from `get_histories()` |
| queue | Sequences/Experiments/Actions | **lazy** `backend.get_queue_object(kind, idx)` |
| queue | Action Servers | `self.vis.world_cfg["servers"][name]` (local) |

History full dicts are retained per-tab (keyed by row order) when `get_history()`
refreshes, so selection can resolve them without a backend round-trip.

### 1.4 Backend addition

Add to the backend contract (`OrchBackend`) and both implementations:

- `async get_queue_object(kind: str, idx: int) -> dict`
  - `kind` ∈ {`"sequence"`, `"experiment"`, `"action"`}.
  - **Local** (`OrchBackend`): index the corresponding orch deque
    (`sequence_dq`/`experiment_dq`/`action_dq`), return `.as_dict()`.
  - **Remote** (`RemoteBackend`): call a new OrchAPI GET endpoint
    `/get_queue_object` with `kind` + `idx`, returning the full JSON-safe dict.
  - Out-of-range `idx` → return `{}` (queue may have mutated since poll; snapshot
    semantics are acceptable).

New OrchAPI endpoint on the orchestrator server mirrors the existing
`/move_sequence` / `/remove_sequence` additions.

### 1.5 Selection & tab reactivity

- One render function per side (planhistory, queue):
  1. read active tab index from the `Tabs`,
  2. read selected indices from that tab's table `source.selected.indices`,
  3. resolve the object (local lookup or lazy backend fetch),
  4. set the tree header `Div.text` and tree `Div.text`.
- Wiring:
  - each table `source.selected.on_change("indices", render_fn)`,
  - each `Tabs.on_change("active", render_fn)`.
- Lazy fetches run via `doc.add_next_tick_callback` (async backend call).
- Poll refresh reassigns/streams `source.data`, which clears selection; the tree then
  falls back to its placeholder until the user re-selects. Acceptable.

### 1.6 Layout

- Root `dynamic_col` → `sizing_mode="stretch_width"`; the width-capped sub-layouts
  that currently set `width=self.max_width` switch to stretch so they expand to the
  browser width.
- Replace the `[self.planhistory_tabs]` and `[self.queue_tabs]` rows with
  `row([tabs, column([header_div, tree_div])])`, both halves `sizing_mode="stretch_width"`
  for a 50/50 split. (May need explicit equal flex / wrapper columns to enforce 50/50.)
- Tables drop their fixed `width` and use `sizing_mode="stretch_width"`.
- Button rows, dropdowns, and metadata inputs keep their fixed sizes and left-align
  within the now-wider column.

## Feature 2 — Parameter input enumeration (independent)

In `add_dynamic_inputs` (`bokeh_operator.py` ~line 1873), change the label `Div` text
from:

```
f"{args[idx]} <i>[{type_hint}]</i>"
```

to:

```
f"{idx}) {args[idx]} <i>[{type_hint}]</i>"
```

- `idx` (0-based loop variable) is the enumeration index.
- Cosmetic only: widget key remains on `text_input.name = args[idx]` (the `.name`
  decoupling from commit 7e4c5bf2), so param read/write is unaffected.
- Separate commit from the datacube work.

## Testing

Run via the existing standalone-operator test harness (drain-callbacks pattern), plus
`run_unit_tests.py` for the whole branch.

- `_object_to_html`: params open + others closed; nested dict; nested list with index
  labels; scalar leaf; empty dict/list; action-server config opens `params`.
- Tree header text for each object type (object → name·uuid8; server → name·host:port);
  placeholder when no selection.
- `get_queue_object` on local `OrchBackend`: valid idx returns full dict; out-of-range
  returns `{}`.
- Selection → tree integration: select a row in each tab, assert header + tree text;
  tab switch re-renders.
- Param-label enumeration: assert label text starts with `"0) "` and that the widget
  `.name` (key) is unchanged.

## Risks & notes

- Widening the root touches the carefully tuned dynamic parameter layout; watch the
  known Bokeh Tabs "tallest panel reserves height" whitespace gotcha when sizing modes
  change.
- 50/50 split via twin `stretch_width` children may not be exactly even; may need
  explicit flex weights or wrapper columns.
- Large objects (sequences with many experiments/actions) still ship full DOM even when
  collapsed; default-collapse keeps them visually compact but the HTML is present.
- Lazy queue `idx` can shift if the queue mutates between poll and click — snapshot
  semantics, returns `{}` on miss.
- HTE plate-map code paths are not exercised by the Linux test suite; layout changes
  near the param block need a separate HTE smoke check.

## Out of scope

- Editing objects from the tree (read-only).
- Replacing existing tables or queue-control buttons.
- Any change to `DataCube`/grouping/aggregation (not used).
