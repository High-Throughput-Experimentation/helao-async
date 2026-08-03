# Reflex Operator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A full-fidelity Reflex operator on `/operator`, driven by the same `OrchBackend` the Bokeh operator uses, with the Bokeh operator still working.

**Architecture:** `orch_backend.py` is already an async ABC with 25 methods; the Reflex operator is a second consumer of it. Two pieces of tricky pure logic are extracted from `bokeh_operator.py` into `param_forms.py` and shared. The page is four `rx.State` subclasses — queue, plan, library, plate — that talk to the backend rather than to each other.

**Tech Stack:** Reflex 0.9.7, xy 0.0.5 via `helao.core.servers.reflex.plots`, pytest, Playwright (headless chromium, installed).

## Global Constraints

- **`test_standalone_operator.py` (48 tests) stays green with no edits.** A test changed to accommodate the extraction means the extraction changed behaviour — that is a failed task, not a fixed test.
- **`orch_backend.py` and `helao_operator.py` are not edited.** The Reflex operator consumes `OrchBackend`; if it needs something the ABC lacks, that is a spec question, not a licence to edit.
- **`bokeh_operator.py` is edited only to import from `param_forms`** and keep thin wrappers. No other change.
- **State is split per tab group** (`OperatorQueueState`, `OperatorPlanState`, `OperatorLibState`, `OperatorPlateState`). No cross-state var references.
- **Reflex vars that `rx.foreach` iterates need element annotations** — `list[list[str]]`, never bare `list`. A bare list fails the *frontend build* with `ForeachVarError`, not at import.
- **Table row selection is the checkbox-column idiom** from `data_browser/app_reflex.py`; `rx.data_table` has no selection callback.
- **Non-numeric columns never reach `plots`** — a string column raises inside the render and takes down the whole chart.
- **Anything skipped or refused is named** in the status line, with the reason.
- Python is `/home/dan/miniforge3/envs/helao/bin/python`. Run `black` on changed files immediately before every `git add`. `pyright` (basic) is authoritative. One pytest file per process.

## File Structure

| File | Responsibility |
|---|---|
| `helao/core/servers/operator/param_forms.py` (new) | Extracted pure logic: docstring parsing, library introspection, version hints, parameter typing. |
| `helao/core/servers/operator/bokeh_operator.py` (edit) | Imports the above; wrappers preserve its method surface. |
| `helao/core/servers/operator/app_reflex.py` (new) | The four states and the page. |
| `helao/core/servers/reflex/app.py` (edit) | `/operator` resolves to the real page. |
| `helao/core/tests/test_operator_param_forms.py` (new) | Direct coverage of the extracted functions. |
| `helao/core/tests/test_reflex_operator.py` (new) | State transitions against a fake backend. |
| `helao/core/tests/browser_check_operator.py` (new) | Live render check. |

---

### Task 1: Extract `param_forms.py`

**Files:**
- Create: `helao/core/servers/operator/param_forms.py`
- Modify: `helao/core/servers/operator/bokeh_operator.py`
- Test: `helao/core/tests/test_operator_param_forms.py`

**Interfaces:**
- Produces: `parse_arg_docs(doc) -> dict[str, str]`, `build_lib(lib, filter_type, config_key, world_cfg, model_class, name_field, codehash_map=None) -> tuple[list, list]`, `version_hint_parts(item) -> list[str]`.
- Consumed by Task 4 and by `bokeh_operator.py`.

**The rule for this task:** move the bodies verbatim. Behaviour changes are out of scope even where the code looks improvable — the 48 tests are the contract, and this task's whole justification is that it does not change what they see.

- [ ] **Step 1: Record the baseline**

Run: `/home/dan/miniforge3/envs/helao/bin/python -m pytest -q helao/core/tests/test_standalone_operator.py`
Expected: all 48 pass. Note the number; it must be identical at Step 6.

- [ ] **Step 2: Write tests for the extracted surface**

Create `helao/core/tests/test_operator_param_forms.py`. These cover the functions *directly*, which the Bokeh class only reached through UI callbacks:

```python
"""Tests for the operator's pure parameter-form logic.

Extracted from bokeh_operator so the Reflex operator can share it rather than
grow a second docstring parser that drifts. These test it directly; the Bokeh
operator's own suite reaches it only through UI callbacks.
"""

import pytest

from helao.core.servers.operator import param_forms as pf


def test_parse_arg_docs_reads_a_plain_args_section():
    doc = "Summary.\n\nArgs:\n    alpha: first thing\n    beta: second thing\n"
    assert pf.parse_arg_docs(doc) == {"alpha": "first thing", "beta": "second thing"}


def test_parse_arg_docs_accepts_a_type_in_parentheses():
    doc = "Args:\n    alpha (int): a count\n"
    assert pf.parse_arg_docs(doc) == {"alpha": "a count"}


def test_parse_arg_docs_folds_continuation_lines():
    doc = "Args:\n    alpha: first line\n        second line\n"
    assert "second line" in pf.parse_arg_docs(doc)["alpha"]


def test_parse_arg_docs_stops_at_the_next_section():
    doc = "Args:\n    alpha: a thing\n\nReturns:\n    something else\n"
    parsed = pf.parse_arg_docs(doc)
    assert set(parsed) == {"alpha"}


def test_parse_arg_docs_skips_varargs():
    doc = "Args:\n    *args: ignored\n    **kwargs: ignored\n    alpha: kept\n"
    assert set(pf.parse_arg_docs(doc)) == {"alpha"}


def test_parse_arg_docs_on_no_docstring_is_empty():
    assert pf.parse_arg_docs("") == {}
    assert pf.parse_arg_docs(None) == {}


def test_version_hint_parts_includes_version_and_codehash():
    assert pf.version_hint_parts({"version": 2, "codehash": "abc"}) == ["v2", "abc"]


def test_version_hint_parts_omits_what_is_absent():
    assert pf.version_hint_parts({"version": 1}) == ["v1"]
    assert pf.version_hint_parts({"codehash": "abc"}) == ["abc"]
    assert pf.version_hint_parts({}) == []
```

- [ ] **Step 3: Run them and watch them fail**

Run: `/home/dan/miniforge3/envs/helao/bin/python -m pytest -q helao/core/tests/test_operator_param_forms.py`
Expected: FAIL at import — `ModuleNotFoundError: ... param_forms`.

- [ ] **Step 4: Create `param_forms.py` by moving the bodies**

Create the module with a docstring stating why it exists, then move — unchanged — the bodies of `BokehOperator._parse_arg_docs` (line ~1236), `BokehOperator._build_lib` (line ~1144) and `BokehOperator._version_hint` (line ~1276).

Three mechanical adjustments, and no others:

1. `parse_arg_docs` and `version_hint_parts` are already `@staticmethod`; drop the decorator and the indentation.
2. `_build_lib` reads `self.vis.world_cfg`; take `world_cfg` as an explicit parameter instead. Everything else it touches is already an argument.
3. `_version_hint` returns HTML. Split it: `version_hint_parts(item)` returns the plain parts, and the Bokeh wrapper does the escaping and `<i>` wrapping.

```python
def version_hint_parts(item: dict) -> list:
    """Return the ``["v2", "abc123"]`` parts of a selector's version hint.

    Plain strings, no markup: the Bokeh operator wraps and escapes these for a
    ``Div``, and the Reflex operator renders them as text. Escaping in here
    would put HTML in the Reflex UI.
    """
    parts = []
    version = item.get("version")
    if version is not None:
        parts.append(f"v{version}")
    codehash = item.get("codehash")
    if codehash:
        parts.append(str(codehash))
    return parts
```

- [ ] **Step 5: Point `bokeh_operator.py` at it**

Delete the three method bodies and replace with wrappers that preserve the existing call sites (lines 1442, 1545, 1556, 1710, 1719, 2589 — including `BokehOperator._parse_arg_docs(doc)` called on the *class*, so that wrapper stays a `staticmethod`):

```python
from helao.core.servers.operator.param_forms import (
    build_lib,
    parse_arg_docs,
    version_hint_parts,
)

    # ... inside BokehOperator:

    _parse_arg_docs = staticmethod(parse_arg_docs)

    def _build_lib(self, lib, filter_type, config_key, model_class, name_field,
                   codehash_map=None):
        """See :func:`~helao.core.servers.operator.param_forms.build_lib`."""
        return build_lib(
            lib, filter_type, config_key, self.vis.world_cfg, model_class,
            name_field, codehash_map,
        )

    @staticmethod
    def _version_hint(item: dict) -> str:
        """Format the 'version · codehash' hint shown beside a selector dropdown."""
        # Every part is escaped, not just the codehash as before: the version
        # part is `v` plus a number, so escaping it is a no-op and the output is
        # byte-identical -- while removing the question of which part was safe.
        parts = [_html.escape(p) for p in version_hint_parts(item)]
        return f"<i>{' · '.join(parts)}</i>" if parts else ""
```

- [ ] **Step 6: Prove nothing changed**

Run: `/home/dan/miniforge3/envs/helao/bin/python -m pytest -q helao/core/tests/test_operator_param_forms.py`
Expected: PASS.

Run: `/home/dan/miniforge3/envs/helao/bin/python -m pytest -q helao/core/tests/test_standalone_operator.py`
Expected: **the same 48 passing, with the file unedited.** If a test now fails, revert and re-do the move — do not adjust the test.

- [ ] **Step 7: Format and commit**

```bash
/home/dan/miniforge3/envs/helao/bin/black helao/core/servers/operator/param_forms.py helao/core/servers/operator/bokeh_operator.py helao/core/tests/test_operator_param_forms.py
git add helao/core/servers/operator/param_forms.py helao/core/servers/operator/bokeh_operator.py helao/core/tests/test_operator_param_forms.py
git commit -m "refactor(operator): extract parameter-form logic for both UIs

Google-docstring parsing and library introspection are needed verbatim by the
Reflex operator. Reimplementing them would leave two parsers to drift, so they
move to param_forms.py and bokeh_operator imports them.

The 48 tests in test_standalone_operator.py pass unedited, which is the whole
justification for touching a file 32 configs depend on."
```

---

### Task 2: Queue state — status, tables, polling

**Files:**
- Create: `helao/core/servers/operator/app_reflex.py`
- Test: `helao/core/tests/test_reflex_operator.py`

**Interfaces:**
- Consumes: `OrchBackend` (`get_orch_state`, `get_status_summary`, `list_sequences`, `list_experiments`, `list_actions`, `subscribe`).
- Produces: `make_backend(world_cfg, server_key)`, `queue_rows(items, columns)`, `status_line(orch_state, reachable)`, `OperatorQueueState`. Tasks 3–6 build on these.

**Why a fake backend:** `OrchBackend` is an ABC, so the test stub is small — and that is the point of Decision 1 beyond code reuse. No orchestrator runs in these tests.

- [ ] **Step 1: Write the failing tests**

Create `helao/core/tests/test_reflex_operator.py`:

```python
"""Tests for the Reflex operator page.

Driven against a fake OrchBackend: the real one is an ABC, so a stub is small,
and no orchestrator runs here. The page's logic lives in module-level functions
for the same reason the browser's does -- rx.State cannot be instantiated
outside a running app.
"""

import pytest

from helao.core.servers.operator import app_reflex as opx


class FakeBackend:
    """Only the OrchBackend methods the page calls."""

    def __init__(self, sequences=None, experiments=None, actions=None, state="idle"):
        self._sequences = sequences or []
        self._experiments = experiments or []
        self._actions = actions or []
        self._state = state
        self.calls = []

    async def get_orch_state(self):
        return {"orch_state": self._state, "loop_state": "started"}

    async def list_sequences(self):
        return self._sequences

    async def list_experiments(self):
        return self._experiments

    async def list_actions(self):
        return self._actions

    async def start(self):
        self.calls.append("start")

    async def stop(self, reset_run_id=False):
        self.calls.append(("stop", reset_run_id))

    async def estop(self):
        self.calls.append("estop")


def test_queue_rows_renders_requested_columns_as_strings():
    """Reflex serialises state to JSON; a UUID or None in a cell breaks the
    encoder or renders as garbage."""
    items = [{"a": 1, "b": None, "c": "x"}]
    assert opx.queue_rows(items, ["a", "b"]) == [["1", ""]]


def test_queue_rows_tolerates_a_missing_column():
    assert opx.queue_rows([{"a": 1}], ["a", "nope"]) == [["1", ""]]


def test_queue_rows_on_nothing_is_empty():
    assert opx.queue_rows([], ["a"]) == []


def test_status_line_reports_the_orchestrator_state():
    assert "idle" in opx.status_line({"orch_state": "idle"}, reachable=True)


def test_status_line_distinguishes_unreachable_from_idle():
    """A station's orchestrator restarting mid-session is routine, and 'idle'
    would be a lie about it."""
    line = opx.status_line(None, reachable=False)
    assert "idle" not in line
    assert "reach" in line.lower()
```

- [ ] **Step 2: Run and watch fail**

Run: `/home/dan/miniforge3/envs/helao/bin/python -m pytest -q helao/core/tests/test_reflex_operator.py`
Expected: FAIL at import.

- [ ] **Step 3: Create `app_reflex.py` with the helpers and queue state**

Module docstring must state the two facts a reader needs: it consumes `OrchBackend`, and the state is split per tab group because Reflex re-renders on any var change in a state.

Helpers:

```python
def queue_rows(items: list, columns: list) -> list:
    """Render backend queue objects as table rows.

    Every cell is a string. Reflex serialises state to JSON, and a UUID, a
    None, or a nested dict reaches the browser as garbage or breaks the
    encoder outright.
    """
    return [
        [("" if item.get(col) is None else str(item.get(col))) for col in columns]
        for item in items
    ]


def status_line(orch_state, reachable: bool) -> str:
    """One line describing the orchestrator.

    ``reachable`` is separate from the state because RemoteBackend polls over
    HTTP and a station's orchestrator restarting mid-session is routine --
    reporting that as "idle" would be a lie about it.
    """
    if not reachable:
        return "cannot reach the orchestrator"
    state = (orch_state or {}).get("orch_state", "unknown")
    loop = (orch_state or {}).get("loop_state", "")
    return f"orchestrator {state}" + (f" (loop {loop})" if loop else "")
```

`OperatorQueueState` carries: `orch_state_text`, `reachable`, `seq_rows`, `exp_rows`, `act_rows`, `server_rows` (all `list[list[str]]`), `error: str`, and `polling: bool`. Its one `@rx.event(background=True)` `poll_loop` refreshes all four tables at the config's `poll_interval` (default 5s), mirroring the Bokeh operator. Control handlers `start`, `stop`, `estop`, `skip`, `clear_sequences`, `clear_experiments`, `clear_actions` call the backend and set `error` on failure.

The backend instance lives in a module-level per-session registry — the same shape as `data_browser.app_reflex.IndexCache` — not in a state var, because it holds sockets.

- [ ] **Step 4: Run the tests** — Expected: PASS.

- [ ] **Step 5: Format and commit**

```bash
git commit -m "feat(operator): queue state, tables and orchestrator polling

Consumes the OrchBackend ABC rather than reimplementing orchestrator
communication. Reachability is tracked separately from orchestrator state: a
station's orchestrator restarting mid-session is routine, and reporting that
as 'idle' would be a lie about it."
```

---

### Task 3: Queue controls and reordering

**Files:** modify `app_reflex.py`; extend `test_reflex_operator.py`.

**Interfaces:** consumes `move_sequence`, `remove_sequence`, `move_experiment`, `remove_experiment`, `move_action`, `remove_action`; produces `moved_index(kind, positions, direction, length)` plus the handlers.

The Bokeh operator gates its queue buttons on orchestrator state (`test_queue_controls_enable_gate`, `test_queue_button_dispatch_routing`). Port that gating: the enable predicate is pure and testable.

- [ ] **Step 1:** Tests for `moved_index` (up at position 0 is a no-op, down at the end is a no-op, a valid move returns the target) and for the enable predicate, including the case the Bokeh suite covers.
- [ ] **Step 2:** Run, watch fail.
- [ ] **Step 3:** Implement the pure helpers plus handlers that call the backend and refresh via the poll loop rather than mutating rows locally — the orchestrator is the source of truth, and a local edit that the next poll contradicts is worse than a slower update.
- [ ] **Step 4:** Run tests. **Step 5:** black, commit.

---

### Task 4: Libraries and the dynamic parameter form

**Files:** modify `app_reflex.py`; extend `test_reflex_operator.py`.

**Interfaces:** consumes Task 1's `build_lib`, `parse_arg_docs`, `version_hint_parts`, and `backend.add_sequence` / `unpack_sequence`.

This is the task with the most behaviour in it. `OperatorLibState` holds the sequence/experiment/spec selection, and a `param_fields: list[dict]` describing each input — name, kind (`text`/`number`/`bool`/`select`), default, options, help text from `parse_arg_docs`.

Rendering is `rx.foreach` over `param_fields`, so **`param_fields` needs a concrete element annotation** or the frontend build fails with `ForeachVarError`. Reflex cannot iterate `list[dict]` with heterogeneous value types either — flatten each field to `list[str]` (`[name, kind, value, help]`) and keep the typed values in a parallel backend var.

- [ ] **Step 1:** Tests for `fields_for_item(item, arg_descs)` (typed defaults become the right kind; a param with no annotation falls back to text; the `Experiment`/`Sequence` framework arg is dropped), and for `coerce_params(fields, values)` (a value that will not coerce is reported, not silently dropped — the constraint from the spec).
- [ ] **Step 2:** Run, watch fail. **Step 3:** Implement. **Step 4:** Run. **Step 5:** black, commit.

---

### Task 5: Plan tab and history tabs

**Files:** modify `app_reflex.py`; extend `test_reflex_operator.py`.

`OperatorPlanState` ports the plan buffer the Bokeh suite covers in `test_plan_buffer_append_and_wrap`, `test_plan_buffer_order`, `test_plan_table_rows`, `test_plan_reorder_and_remove`, `test_flush_add_dispatches_per_sequence`, `test_prepend_plan_callback_clears_and_dispatches`. Read those six tests first: they are the specification of this tab's behaviour, and the Reflex version must match it.

History tabs render `backend.get_histories()` through `queue_rows`.

- [ ] Steps as above: tests mirroring the six Bokeh behaviours, then implementation, then commit.

---

### Task 6: Plate map

**Files:** modify `app_reflex.py`; extend `test_reflex_operator.py`.

`OperatorPlateState` holds `plate_id`, `sample_no`, and the map. The chart is `plots.scatter_map(x, y, values=..., panel_id=..., version=...)` with `on_select` wired to a handler that sets `sample_no` — Decision 6; no new xy surface.

Two constraints carried from earlier ports: the buffer-store key is session-scoped (`f"plate-{token}"`), and **coordinates are filtered for numeric content before they reach `plots`**.

The Bokeh suite has `test_plate_api_disabled_by_default` and `test_plate_callbacks_noop_when_plate_api_disabled`: the plate API is opt-in. Port that gate — with it disabled, the tab renders an explanatory note, not a broken map.

- [ ] Steps as above.

---

### Task 7: Route, bundle, and a live browser check

**Files:** modify `helao/core/servers/reflex/app.py`; create `helao/core/tests/browser_check_operator.py`; modify `CLAUDE.md`.

- [ ] **Step 1:** Wire `/operator` to `build_page()`, importing the four state classes at module scope — `--backend-only` never evaluates the page callable, and Reflex registers event handlers at class creation, so a class first touched inside it leaves every control silently dead. Add the same registration test the browser has.
- [ ] **Step 2:** Rebuild the bundle. `/mnt/STORAGE` is `noexec`, so stage in `/tmp` (the exact sequence is in the data-browser plan, Task 5 Step 1). **Verify `frontend.zip` exists before deleting the old bundle** — an export can fail silently, and removing a working bundle first leaves nothing to serve.
- [ ] **Step 3:** Write `browser_check_operator.py`: load `/operator` against a live `goldenreflex` group, select a sequence, fill a parameter, enqueue, and assert the queue table shows it. Use `.click()` on checkboxes, not `.check()` — Radix renders `<button role="checkbox">` and Playwright's `.check()` waits on a contract it does not satisfy.
- [ ] **Step 4:** Run it against a launched group. Expected: `PASS`.
- [ ] **Step 5:** Document in `CLAUDE.md`: the operator has two UIs over one `OrchBackend`, and `param_forms.py` is shared by both.
- [ ] **Step 6:** black, commit.

---

## Risks

- **The extraction is the one place this plan can break production.** Task 1 is deliberately first, small, and gated on 48 unedited tests.
- **Task 4 is the largest.** If it overruns, the honest split is dynamic parameter forms in one task and library selection in another — not a reduced-fidelity form, which the spec rules out.
- **Reflex's `foreach` over heterogeneous structures** is the most likely build-time surprise, and it surfaces only at `reflex export`. Task 4 flattens to `list[str]` for that reason.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-02-reflex-operator.md`. Two execution options:

**1. Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks.

**2. Inline Execution** — execute tasks in this session with checkpoints.

Which approach?
