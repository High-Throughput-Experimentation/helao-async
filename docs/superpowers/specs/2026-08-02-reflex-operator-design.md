# Reflex operator — design

**Status:** design, not yet implemented.
**Branch:** `feat/reflex-operator`, off `feat/reflex-data-browser`.
**Parent spec:** `docs/superpowers/specs/2026-08-01-reflex-ui-design.md`, which built the
Reflex/xy foundation, left `/operator` as a stub, and reserved this port for its
own spec. Decision 1 there still binds: the Bokeh operator is **not** removed,
deprecated, or replaced. 32 configs name `standalone_operator`; every one keeps
working.

**Scope:** a full-fidelity port. Every surface the Bokeh operator has — queue
tables, the Plan tab, history tabs, sequence/experiment/spec libraries, dynamic
parameter forms, and the clickable plate map — appears in the Reflex operator.
An operator missing a tab is one nobody switches to.

## What is actually being ported

`bokeh_operator.py` is 3077 lines in one class, which the parent spec names as a
development-experience problem in its own right. But the operator is **not**
undifferentiated UI: it already has a backend seam.

| Module | Lines | Bokeh? | Fate |
|---|---:|---|---|
| `orch_backend.py` | 366 | no | **reused verbatim** — `OrchBackend` ABC + `RemoteBackend` |
| `helao_operator.py` | 151 | no | untouched (a separate scripting client) |
| `bokeh_operator.py` | 3077 | **yes** | keeps working; loses ~250 lines to extraction |
| `param_forms.py` | new | no | extracted pure logic, shared by both UIs |

`OrchBackend` is an async ABC of 25 methods — `list_sequences`, `add_sequence`,
`move_experiment`, `start`, `stop`, `estop`, `get_orch_state`, `subscribe`, and
the rest. The Reflex operator talks to exactly that interface, so it inherits
orchestrator communication, run-id handling and queue mutation for free. This is
the same shape that made the data browser port small, and it is why a
3077-line file does not imply a 3077-line port.

## The one risky decision, stated plainly

Two pieces of `bokeh_operator.py` are genuinely tricky pure logic that the
Reflex operator needs verbatim:

- `_parse_arg_docs` — parses Google-style `Args:` sections into per-parameter
  help text, handling `name (type):` forms, continuation lines, and section
  boundaries.
- `_build_lib` — introspects a sequence/experiment library into selectable
  items, dropping framework-injected parameters and overlaying config defaults.

Reimplementing them in the Reflex module means two docstring parsers that drift.
Extracting them means editing a production file that 32 configs depend on.

**Decision: extract, narrowly.** `_parse_arg_docs`, `_build_lib`,
`_version_hint`, and the parameter-typing helpers move to
`helao/core/servers/operator/param_forms.py` as module-level functions;
`bokeh_operator.py` imports them and keeps thin wrappers where its callers
expect methods. Nothing else moves.

What makes this defensible rather than reckless: `test_standalone_operator.py`
is 1476 lines and 48 tests driving the real `BokehOperator` — tables, plate
callbacks, queue-control enable gates, dispatch routing, the plan buffer,
label sanitising. **Those 48 tests must stay green with no edits.** A test
changed to accommodate the extraction is the signal that the extraction changed
behaviour, and is a failed task.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | Reuse `orch_backend.py` untouched | It is already the seam. The Reflex operator is a second consumer of `OrchBackend`, not a second implementation. |
| 2 | Extract only `param_forms.py`; leave the rest of `bokeh_operator.py` alone | Bounded, high-value, covered by 48 existing tests. Broader refactoring of a production operator is not this port's job. |
| 3 | One `rx.State` subclass per *tab group*, not one for the whole page | The page is large. Reflex re-renders on any var change in a state, so a single state makes a keystroke in a parameter field re-push queue tables. Split: `OperatorQueueState`, `OperatorPlanState`, `OperatorLibState`, `OperatorPlateState`. |
| 4 | Backend polling lives in one `@rx.event(background=True)` loop on the queue state | Mirrors the Bokeh `poll_interval` param. One poller, not four, so the four states cannot disagree about orchestrator status. |
| 5 | Parameter inputs are typed `rx.input`/`rx.select`/`rx.checkbox` driven by `param_forms`, and `parse_bokeh_input` is **not** ported | Reflex delivers typed Python. The Bokeh coercion layer exists only because Bokeh hands back strings. |
| 6 | The plate map is `plots.scatter_map` with an `on_select` handler | The facade already has it, including the selection callback. No new xy surface needed. |
| 7 | Selection in queue tables uses the checkbox-column idiom from the browser | `rx.data_table` exposes no row-selection callback. Established and proven in `app_reflex.py`. |
| 8 | Reflex vars that `rx.foreach` iterates carry element annotations | A bare `list` fails the frontend build with `ForeachVarError`, not at import. Learned in the browser port. |
| 9 | Non-numeric columns are filtered before they reach `plots` | Same lesson: a string column raises inside the render and takes down the whole chart. |

## Architecture

```
helao/core/servers/operator/
  orch_backend.py     (unchanged)  <-- OrchBackend ABC + RemoteBackend
  helao_operator.py   (unchanged)
  param_forms.py      (new)        <-- extracted pure logic, both UIs use it
  bokeh_operator.py   (edited)     <-- imports param_forms; still live
  app_reflex.py       (new)        <-- the Reflex page on /operator
```

**State split** (Decision 3), each a plain `rx.State`:

- `OperatorQueueState` — orchestrator status, the four queue tables
  (sequence / experiment / action / action-server), the control buttons, and
  the single polling loop.
- `OperatorPlanState` — the Plan tab's buffer, reorder/remove, flush/prepend.
- `OperatorLibState` — sequence / experiment / spec selection and the dynamic
  parameter form.
- `OperatorPlateState` — plate id, sample no, the plate map and its selection.

The states communicate through the backend, not through each other: enqueuing
from `OperatorLibState` calls `backend.add_sequence`, and the next poll on
`OperatorQueueState` shows it. No cross-state var references, which Reflex makes
awkward and which would reintroduce the coupling this split exists to avoid.

## Error handling

The Bokeh operator writes failures to a status `Div`. The Reflex operator does
the same, per state, and follows the browser's rule: **anything skipped or
refused is named.** A sequence that fails to enqueue, a parameter that will not
coerce, a plate id with no calibration — each says which and why, rather than
leaving a control that looks like it did nothing.

Orchestrator connectivity gets its own treatment: `RemoteBackend` polls over
HTTP, and a station's orchestrator restarting mid-session is routine. The status
line distinguishes "orchestrator idle" from "cannot reach orchestrator".

## Testing

- **`param_forms` extraction.** The existing 48 operator tests stay green,
  unedited. New tests cover the extracted functions directly, which the Bokeh
  class only reached indirectly.
- **State logic, headless.** Each state's transitions driven against a fake
  `OrchBackend` — the ABC makes this a small stub, and it is why Decision 1
  matters beyond code reuse.
- **Route registration.** `/operator` resolves to the real page, not the stub.
- **A live browser check.** Non-negotiable after this port's history: six
  rendering defects in the visualiser port and two more in the browser port
  survived green unit suites because nothing loaded a page. The check drives a
  real `goldenreflex` group: select a sequence, fill a parameter, enqueue,
  start, and assert the queue table shows it.

## Out of scope

- Removing, deprecating or restructuring the Bokeh operator beyond the
  `param_forms` extraction.
- `gcld_operator.py` and other deployment-specific operators.
- New operator features. This is a re-rendering.
