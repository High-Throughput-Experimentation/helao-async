# Reflex Composition Visualizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/composition` page to the Reflex UI stack that loads every XRF process for a plate id from the HELAO metadata API, groups them by `run_use` and sequence, and plots a selected transition and unit as a platemap scatter (with an RBF-interpolated variant) and a ternary diagram, with click-to-inspect showing the sample's analysis output and source spectrum.

**Architecture:** Three layers. `helao/ui/shared/platemap.py` and `helao/ui/shared/composition/` hold every piece of logic that does not import `reflex`, so they are testable without a Reflex app. `helao/ui/reflex/composition.py` is the page. `helao/ui/reflex/plots.py` gains one function and stays the only module importing `xy`.

**Tech Stack:** Python 3.14, Reflex, `xy==0.0.5`, numpy, scipy 1.18, httpx, pytest.

**Spec:** `docs/superpowers/specs/2026-09-22-reflex-composition-visualizer-design.md`

## Global Constraints

- **Environment.** Everything runs in the `helao` conda env. Use
  `/home/dan/miniforge3/envs/helao/bin/python` explicitly; the OS python is a
  different interpreter. `PYTHONPATH` must be the repo root.
- **Test invocation.** One pytest process per file, under `timeout`. Do not run
  the whole tree in one session and do not wrap pytest in `conda run` (it
  buffers output):
  ```bash
  cd /mnt/STORAGE/repos/helao/helao-async
  PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async timeout 600 \
    /home/dan/miniforge3/envs/helao/bin/python -m pytest <file> -v
  ```
- **Formatting.** Run `black` on every changed file immediately before
  `git add`, in every task:
  `/home/dan/miniforge3/envs/helao/bin/black <files>`
- **Branch.** All work lands on `feat/reflex-composition-visualizer`, which
  already exists and already holds the spec commit. Never commit to `unstable`.
  Re-check `git status --short --branch` immediately before every `git add`.
- **Never name a private deployment** in any file in this repo. This is a public
  remote. Say "a private deployment".
- **No hardcoded colours anywhere** except `palette.py` and `bokeh_theme.py`.
  `helao/core/tests/test_palette.py` sweeps the AST and will fail. Reach colour
  through `reflex_page_class`, `reflex_header_class`, `reflex_table_class`,
  `reflex_muted_text_class`.
- **Only `helao/ui/reflex/plots.py` and `helao/ui/reflex/xy_component.py` may
  import `xy`.** A test enforces this.
- **`text-slate-500` is a test failure** in the Reflex stack. Muted text is
  `reflex_muted_text_class()`, which is `slate-600`.
- **No `while True` and no `background=True` polling loop** in the page.
- **Every `rx.foreach` var carries an element annotation** (`list[list[str]]`,
  never bare `list`). A bare `list` fails the frontend build with
  `ForeachVarError`, which surfaces only at `reflex export`.
- **API base URL** is `https://helao-api.caltech-hte.modelyst.com/api` and its
  spec is at `https://helao-api.caltech-hte.modelyst.com/api/openapi.json`.
  Every test in this plan stubs the client; **no test performs a live request**.

---

## File Structure

| File | Responsibility |
|---|---|
| `helao/ui/shared/platemap.py` | **new.** The plate-map helper family, hoisted out of `operator.py` verbatim, plus `plate_api_for_config` and `platemap_rows`. |
| `helao/ui/reflex/operator.py` | **modify.** Delete lines 2461–2581; import the same names back from `shared.platemap`. |
| `helao/ui/shared/composition/__init__.py` | **new.** Empty. |
| `helao/ui/shared/composition/model.py` | **new.** `CompositionRecord` and the parsing of an API process item into one. |
| `helao/ui/shared/composition/api.py` | **new.** The four metadata-API calls and the lazy client. |
| `helao/ui/shared/composition/grouping.py` | **new.** Group keys and labels for the two dropdowns. |
| `helao/ui/shared/composition/ternary.py` | **new.** Barycentric → cartesian, triangle geometry. |
| `helao/ui/shared/composition/interp.py` | **new.** RBF surface over the platemap. |
| `helao/ui/reflex/plots.py` | **modify.** Add `ternary`; extend `__all__`. |
| `helao/ui/shared/palette.py` | **modify.** Add `lime-50` to `TW`, `/composition` to `REFLEX_PAGE_TINTS`. |
| `helao/ui/reflex/composition.py` | **new.** `CompositionState`, `configure`, `build_page`. |
| `helao/ui/reflex/app.py` | **modify.** Route, nav link, `configure_composition`, `add_page`. |
| `helao/core/tests/test_shared_platemap.py` | **new.** |
| `helao/core/tests/test_composition_model.py` | **new.** |
| `helao/core/tests/test_composition_api.py` | **new.** |
| `helao/core/tests/test_composition_grouping.py` | **new.** |
| `helao/core/tests/test_composition_ternary.py` | **new.** |
| `helao/core/tests/test_composition_interp.py` | **new.** |
| `helao/core/tests/test_reflex_composition.py` | **new.** |
| `helao/core/tests/test_reflex_plots.py` | **modify.** Add `ternary` coverage. |
| `helao/core/tests/test_palette.py` | **modify.** Add the measured rows for `lime-50`; rename one test. |
| `helao/core/tests/test_reflex_routes_e2e.py` | **modify.** Add the `/composition` real-page and handler-registration tests. |

---

### Task 1: Hoist the plate-map helpers into a shared module

The composition page needs a plate API, plottable platemap rows and a
nearest-point search. The operator already has all three. Re-implementing them
would give the repo two nearest-neighbour searches and two coordinate coercions
that can disagree about what a plate looks like.

**Files:**
- Create: `helao/ui/shared/platemap.py`
- Modify: `helao/ui/reflex/operator.py:2461-2581` (delete), plus one import
- Test: `helao/core/tests/test_shared_platemap.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `FRACTION_KEYS: tuple[str, ...]`
  - `PLATE_APIS: tuple[str, ...]`
  - `plate_api_for(server_cfg: dict)` → an `HTEPlateAPI` or `None`
  - `plate_api_for_config(world_cfg: dict)` → an `HTEPlateAPI` or `None`
  - `platemap_points(pmdata: Optional[list]) -> tuple[list, list, list]`
  - `platemap_rows(pmdata: Optional[list]) -> list[dict]` with keys
    `sample_no: int`, `x: float`, `y: float`, `entry: dict`
  - `nearest_sample(pmdata: Optional[list], x: float, y: float) -> int | None`
  - `composition_text(entry: Optional[dict]) -> str`
  - `sample_summary(pmdata: Optional[list], sample_no: int) -> dict`

- [ ] **Step 1: Write the failing test**

Create `helao/core/tests/test_shared_platemap.py`:

```python
# helao/core/tests/test_shared_platemap.py
"""The plate-map helpers, after the hoist out of the Reflex operator.

Two of these pin properties the composition page depends on and the operator
never exercised: that `platemap_rows` keys on the platemap's own `sample_no`
rather than on the row's position, and that `plate_api_for_config` keeps the
operator's opt-in gate while needing no single server key.
"""

import pytest

from helao.ui.shared import platemap


#: A platemap whose own sample numbers deliberately disagree with the row
#: order: row 0 is sample 5, row 1 is sample 2. `platemap_points` numbers these
#: 1 and 2; `platemap_rows` must call them 5 and 2.
PM = [
    {"sample_no": 5, "x": 1.0, "y": 2.0, "code": 0, "A": 0.5, "B": 0.5},
    {"sample_no": 2, "x": 3.0, "y": 4.0, "code": 0, "A": 1.0},
    {"sample_no": 9, "x": "not a number", "y": 6.0},
]


def test_platemap_rows_keys_on_the_maps_own_sample_no() -> None:
    rows = platemap.platemap_rows(PM)
    assert [row["sample_no"] for row in rows] == [5, 2]


def test_platemap_rows_drops_a_row_with_an_unusable_coordinate() -> None:
    """Dropped whole, as `platemap_points` already does. Handing a string to
    `plots` raises from inside the render and takes the chart down."""
    rows = platemap.platemap_rows(PM)
    assert len(rows) == 2
    assert 9 not in [row["sample_no"] for row in rows]


def test_platemap_rows_and_platemap_points_disagree_about_numbering() -> None:
    """The whole reason `platemap_rows` exists, asserted rather than assumed."""
    _, _, positional = platemap.platemap_points(PM)
    from_map = [row["sample_no"] for row in platemap.platemap_rows(PM)]
    assert positional == [1, 2]
    assert from_map == [5, 2]
    assert positional != from_map


def test_platemap_rows_carries_the_original_entry() -> None:
    rows = platemap.platemap_rows(PM)
    assert rows[0]["entry"]["A"] == 0.5


def test_platemap_rows_on_an_empty_map() -> None:
    assert platemap.platemap_rows(None) == []
    assert platemap.platemap_rows([]) == []


def test_plate_api_for_config_returns_none_when_no_server_declares_one() -> None:
    cfg = {"servers": {"ORCH": {"params": {}}, "MOTOR": {}}}
    assert platemap.plate_api_for_config(cfg) is None


def test_plate_api_for_config_finds_the_server_that_declares_one(monkeypatch) -> None:
    sentinel = object()
    monkeypatch.setattr(
        platemap,
        "plate_api_for",
        lambda cfg: sentinel if (cfg or {}).get("params") else None,
    )
    cfg = {"servers": {"ORCH": {}, "XRFS": {"params": {"plate_api": "HTEPlateAPI"}}}}
    assert platemap.plate_api_for_config(cfg) is sentinel


def test_plate_api_for_config_tolerates_a_config_without_servers() -> None:
    assert platemap.plate_api_for_config({}) is None
    assert platemap.plate_api_for_config(None) is None


def test_nearest_sample_still_works_after_the_hoist() -> None:
    assert platemap.nearest_sample(PM, 2.9, 4.1) == 2


def test_the_operator_still_exposes_every_hoisted_name() -> None:
    """The hoist must be invisible to the operator's own call sites and to the
    tests that reach these through `helao.ui.reflex.operator`."""
    from helao.ui.reflex import operator

    for name in (
        "FRACTION_KEYS",
        "PLATE_APIS",
        "plate_api_for",
        "platemap_points",
        "nearest_sample",
        "composition_text",
        "sample_summary",
    ):
        assert hasattr(operator, name), name
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async timeout 600 \
  /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_shared_platemap.py -v
```

Expected: collection error, `ModuleNotFoundError: No module named 'helao.ui.shared.platemap'`.

- [ ] **Step 3: Create the shared module by moving the block verbatim**

Read `helao/ui/reflex/operator.py` lines 2461–2581. That range starts at the
comment `# -- plate map ---...` and ends with the closing brace of
`sample_summary`, immediately before `class OperatorPlateState(rx.State):` on
line 2583. Move that text unchanged into a new
`helao/ui/shared/platemap.py` under this header:

```python
# helao/ui/shared/platemap.py
"""Plate-map helpers shared by the Reflex operator and the composition page.

Hoisted out of `helao/ui/reflex/operator.py`, where they were written for the
operator's plate tab. Nothing about them is operator-specific: they turn an
`HTEPlateAPI` platemap into plottable points, and resolve a click back to a
sample. `operator.py` imports them back under their existing names, so its call
sites and the tests that reach them through it are unchanged.

This module imports no `reflex`, which is what makes it testable without an app.

Two properties are load-bearing and easy to break:

* `platemap_points` numbers samples **positionally** (`index + 1`), not from the
  platemap's own `sample_no` column. That is the operator's existing behaviour
  and is left alone. Anything joining against records that carry a real sample
  number must use `platemap_rows` instead.
* `plate_api_for` is **opt-in**: no `params.plate_api` means no plate API, and
  an unrecognised value is ignored rather than imported, so a typo cannot pull
  in something arbitrary.
"""

from typing import Optional

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
```

Then append the two new functions:

```python
def plate_api_for_config(world_cfg: Optional[dict]):
    """The first plate API any server in *world_cfg* declares, or ``None``.

    `/composition` binds to no server, so there is no single ``server_cfg`` to
    read ``params.plate_api`` from. Scanning preserves the opt-in property: a
    config where nothing declares one still yields ``None``.
    """
    servers = ((world_cfg or {}).get("servers")) or {}
    for server_cfg in servers.values():
        api = plate_api_for(server_cfg)
        if api is not None:
            return api
    return None


def platemap_rows(pmdata: Optional[list]) -> list:
    """Plottable platemap rows, each keyed by the map's own ``sample_no``.

    The same rows :func:`platemap_points` keeps -- coordinates coerced,
    unconvertible rows dropped whole -- but carrying the sample number the
    platemap itself records rather than the row's position. A caller joining
    against records whose sample number came from somewhere else (an API label,
    a filename) must use this; `platemap_points`' positional numbering would
    silently pair the right value with the wrong position.

    Args:
        pmdata: The platemap, as `HTEPlateAPI.get_platemap_plateid` returns it.

    Returns:
        list: ``{"sample_no": int, "x": float, "y": float, "entry": dict}``.
    """
    rows = []
    for entry in pmdata or []:
        item = entry or {}
        x = _as_number(item.get("x"))
        y = _as_number(item.get("y"))
        if x is None or y is None:
            continue
        raw = item.get("sample_no")
        if raw is None:
            raw = item.get("Sample")
        try:
            sample_no = int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        rows.append({"sample_no": sample_no, "x": x, "y": y, "entry": item})
    return rows
```

- [ ] **Step 4: Point the operator back at the shared module**

Delete lines 2461–2581 of `helao/ui/reflex/operator.py`. In their place put:

```python
# -- plate map ---------------------------------------------------------------
#
# Hoisted to `helao.ui.shared.platemap` so the composition page can use the
# same helpers. Re-exported here under their existing names: every call site
# below, and every test that reaches these through this module, is unchanged.
from helao.ui.shared.platemap import (  # noqa: E402
    FRACTION_KEYS,
    PLATE_APIS,
    composition_text,
    nearest_sample,
    plate_api_for,
    platemap_points,
    sample_summary,
)
```

`_as_number` and `_PLATE_API_CACHE` are private to the shared module and are
not re-exported. Check whether anything else in `operator.py` calls
`_as_number` — `OperatorPlateState.on_select` does. Import it too:

```python
from helao.ui.shared.platemap import _as_number  # noqa: E402
```

- [ ] **Step 5: Run the new test and the operator's own suites**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
export PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async
P=/home/dan/miniforge3/envs/helao/bin/python
timeout 600 $P -m pytest helao/core/tests/test_shared_platemap.py -v
timeout 900 $P -m pytest helao/core/tests/test_reflex_operator.py -q
timeout 900 $P -m pytest helao/core/tests/test_standalone_operator.py -q
timeout 900 $P -m pytest helao/core/tests/test_reflex_routes_e2e.py -q
```

Expected: all PASS. `test_standalone_operator.py` is 59 tests and must pass
**with `helao/ui/bokeh/operator.py` unedited**.

- [ ] **Step 6: Format and commit**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
/home/dan/miniforge3/envs/helao/bin/black \
  helao/ui/shared/platemap.py helao/ui/reflex/operator.py \
  helao/core/tests/test_shared_platemap.py
git status --short --branch
git add helao/ui/shared/platemap.py helao/ui/reflex/operator.py \
  helao/core/tests/test_shared_platemap.py
git commit -m "refactor(ui): hoist the plate-map helpers into a shared module

The composition page needs a plate API, plottable platemap rows and a
nearest-point search; the operator already had all three. Moving them out
rather than re-implementing keeps one nearest-neighbour search and one
coordinate coercion in the repo. operator.py imports the same names back, so
its call sites and its suites are untouched.

Two additions: plate_api_for_config, because a page that binds to no server has
no single server_cfg to read params.plate_api from, and platemap_rows, because
platemap_points numbers samples positionally rather than from the platemap's
own sample_no column -- which is fine for the operator and wrong for anything
joining against records that carry a real sample number.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: `CompositionRecord` and process parsing

**Files:**
- Create: `helao/ui/shared/composition/__init__.py` (empty)
- Create: `helao/ui/shared/composition/model.py`
- Test: `helao/core/tests/test_composition_model.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `CompositionRecord` — frozen dataclass, fields listed in Step 3
  - `NON_NUMERIC_COLUMNS: frozenset[str]`
  - `sample_no_from(process_params: dict) -> int | None`
  - `record_from_process(item: dict, sequences: dict) -> CompositionRecord | None`
  - `with_values(record: CompositionRecord, quant: dict) -> CompositionRecord`
  - `unit_names(records: list[CompositionRecord]) -> list[str]`
  - `transition_names(records: list[CompositionRecord]) -> list[str]`

- [ ] **Step 1: Write the failing test**

Create `helao/core/tests/test_composition_model.py`:

```python
# helao/core/tests/test_composition_model.py
"""Turning a metadata-API process item into a CompositionRecord.

The fixtures here are trimmed copies of real responses captured from the
production metadata API for plate 10244 on 2026-09-22. Nothing in this file
performs a request.
"""

import pytest

from helao.ui.shared.composition import model


PROCESS_ITEM = {
    "process_uuid": "06a7e382-ee08-786f-8000-c6d582f2c3bc",
    "process_timestamp": "2026-08-13T11:57:41.000000",
    "process_name": "xrfs_nostds",
    "run_use": "pre_anneal",
    "sequence_uuid": "06a7e382-a773-731d-8000-d7e3e21eacec",
    "process_params": {
        "plate_id": 10244,
        "source_csv_label": "legacy__solid__10244_42",
        "stage_label": "42",
    },
    "files": [
        {
            "file_type": "edax_orbis_spc__file",
            "file_name": "asdep6.SPC",
            "action_uuid": "06a7e382-ee08-7843-8000-e3562725efd8",
        },
        {
            "file_type": "xrfs_quant_helao__json_file",
            "file_name": "xrfs_nostds-0.0.0.0__2.hlo.json",
            "action_uuid": "06a7e382-ee08-7843-8000-e3562725efd8",
        },
        {
            "file_type": "xrfspec_helao__json_file",
            "file_name": "xrfs_nostds-0.0.0.0__1.hlo.json",
            "action_uuid": "06a7e382-ee08-7843-8000-e3562725efd8",
        },
    ],
}

SEQUENCES = {
    "06a7e382-a773-731d-8000-d7e3e21eacec": {
        "sequence_uuid": "06a7e382-a773-731d-8000-d7e3e21eacec",
        "sequence_timestamp": "2026-08-13T11:54:21.000000",
        "sequence_label": "CoYPt-102441",
    }
}

QUANT = {
    "element": ["Co", "Y", "Y", "Pt", "Pt"],
    "transition": ["Co.K", "Y.K", "Y.L", "Pt.L", "Pt.M"],
    "net_counts": [271.2, 792.1, 1259.2, 44.7, 441.6],
    "nanomoles": [16.4, 79.8, 102.4, 1.9, 12.8],
    "atomic_fraction": [0.167, 0.814, None, 0.019, None],
    "global_sample_label": ["legacy__solid__10244_42"],
    "analysis_name": ["XRFS_quantification_analysis"],
    "output_type": ["composition.xrfs_quantification"],
    "calibration_date": ["2026-06-03"],
}


def test_sample_no_comes_from_the_source_csv_label() -> None:
    assert model.sample_no_from({"source_csv_label": "legacy__solid__10244_42"}) == 42


def test_sample_no_falls_back_to_stage_label() -> None:
    assert model.sample_no_from({"stage_label": "42"}) == 42


def test_sample_no_is_none_when_neither_is_usable() -> None:
    """A record with no sample number is dropped, never plotted at an invented
    position."""
    assert model.sample_no_from({}) is None
    assert model.sample_no_from({"source_csv_label": "no_digits_here_"}) is None
    assert model.sample_no_from({"stage_label": "centre"}) is None


def test_record_from_process_reads_both_file_roles() -> None:
    record = model.record_from_process(PROCESS_ITEM, SEQUENCES)
    assert record is not None
    assert record.quant_file_name == "xrfs_nostds-0.0.0.0__2.hlo.json"
    assert record.spectrum_file_name == "xrfs_nostds-0.0.0.0__1.hlo.json"
    assert record.quant_action_uuid == "06a7e382-ee08-7843-8000-e3562725efd8"


def test_record_from_process_carries_the_sequence_timestamp() -> None:
    """PROCESS records carry a null sequence_timestamp; it comes from the
    separate SEQUENCE search."""
    record = model.record_from_process(PROCESS_ITEM, SEQUENCES)
    assert record.sequence_timestamp == "2026-08-13T11:54:21.000000"


def test_record_from_process_survives_an_unknown_sequence() -> None:
    record = model.record_from_process(PROCESS_ITEM, {})
    assert record is not None
    assert record.sequence_timestamp == ""


def test_record_from_process_returns_none_without_a_sample_number() -> None:
    item = {**PROCESS_ITEM, "process_params": {"plate_id": 10244}}
    assert model.record_from_process(item, SEQUENCES) is None


def test_record_from_process_returns_none_without_a_quant_file() -> None:
    item = {
        **PROCESS_ITEM,
        "files": [f for f in PROCESS_ITEM["files"] if "quant" not in f["file_type"]],
    }
    assert model.record_from_process(item, SEQUENCES) is None


def test_with_values_builds_transition_to_unit() -> None:
    record = model.with_values(model.record_from_process(PROCESS_ITEM, SEQUENCES), QUANT)
    assert record.values["Co.K"]["net_counts"] == pytest.approx(271.2)
    assert record.values["Y.L"]["nanomoles"] == pytest.approx(102.4)


def test_with_values_keeps_a_null_atomic_fraction_as_none() -> None:
    """Y.L and Pt.M are uncalibrated. None is the honest value; 0.0 would plot."""
    record = model.with_values(model.record_from_process(PROCESS_ITEM, SEQUENCES), QUANT)
    assert record.values["Y.L"]["atomic_fraction"] is None
    assert record.values["Y.K"]["atomic_fraction"] == pytest.approx(0.814)


def test_with_values_drops_the_non_numeric_columns() -> None:
    """Handing a string column to `plots` raises from inside the render and
    takes the whole chart down."""
    record = model.with_values(model.record_from_process(PROCESS_ITEM, SEQUENCES), QUANT)
    for unit in record.values["Co.K"]:
        assert unit not in model.NON_NUMERIC_COLUMNS


def test_with_values_ignores_a_column_shorter_than_the_transitions() -> None:
    """`global_sample_label` has one entry for five transitions. A zip would
    silently truncate every other unit to one value."""
    record = model.with_values(model.record_from_process(PROCESS_ITEM, SEQUENCES), QUANT)
    assert len(record.values) == 5


def test_unit_and_transition_names_are_the_union_sorted() -> None:
    a = model.with_values(model.record_from_process(PROCESS_ITEM, SEQUENCES), QUANT)
    b = model.with_values(
        model.record_from_process(PROCESS_ITEM, SEQUENCES),
        {"transition": ["Fe.K"], "net_counts": [1.0]},
    )
    assert model.transition_names([a, b]) == [
        "Co.K",
        "Fe.K",
        "Pt.L",
        "Pt.M",
        "Y.K",
        "Y.L",
    ]
    assert model.unit_names([a, b]) == ["atomic_fraction", "nanomoles", "net_counts"]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async timeout 600 \
  /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_composition_model.py -v
```

Expected: `ModuleNotFoundError: No module named 'helao.ui.shared.composition'`.

- [ ] **Step 3: Write the implementation**

Create an empty `helao/ui/shared/composition/__init__.py`, then
`helao/ui/shared/composition/model.py`:

```python
# helao/ui/shared/composition/model.py
"""One XRF measurement of one sample, as the composition page needs it.

A metadata-API PROCESS item carries everything except two things: the sequence
timestamp (present but null on a process; it comes from a separate SEQUENCE
search) and the analysis values themselves (in an HLO named by the item's
`files` list). `record_from_process` builds the record from the item, and
`with_values` folds in the quantification payload once it has been fetched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Optional

#: Columns of the quantification HLO that are not per-transition measurements.
#: `element` and `transition` are the row identity; the rest are per-file
#: scalars the API returns as one-element lists. Handing any of them to `plots`
#: raises `could not convert string to float` from inside the render, which
#: takes down the whole chart rather than one series.
NON_NUMERIC_COLUMNS = frozenset(
    {
        "element",
        "transition",
        "global_sample_label",
        "analysis_name",
        "output_type",
        "calibration_date",
    }
)

#: The quantification HLO's `file_type`.
QUANT_FILE_TYPE = "xrfs_quant_helao__json_file"

#: The spectrum HLO's `file_type`.
SPECTRUM_FILE_TYPE = "xrfspec_helao__json_file"

#: Trailing sample number of a global label, e.g. `legacy__solid__10244_42`.
_TRAILING_NUMBER = re.compile(r"_(\d+)\s*$")


@dataclass(frozen=True)
class CompositionRecord:
    """One XRF process on one sample.

    Attributes:
        values: ``transition -> unit -> value``. A value is ``None`` where the
            API reported null -- an uncalibrated transition has no
            ``atomic_fraction``, and ``0.0`` there would plot as a measurement.
    """

    plate_id: int
    sample_no: int
    global_label: str
    run_use: str
    sequence_uuid: str
    sequence_timestamp: str
    process_uuid: str
    process_timestamp: str
    quant_action_uuid: str
    quant_file_name: str
    spectrum_action_uuid: str
    spectrum_file_name: str
    values: dict


def sample_no_from(process_params: Optional[dict]) -> Optional[int]:
    """Sample number of one process, or ``None`` when it cannot be determined.

    `source_csv_label` is the global label (`legacy__solid__10244_42`) and is
    tried first; `stage_label` is the fallback. A record that yields neither is
    dropped by :func:`record_from_process` rather than plotted at an invented
    position.
    """
    params = process_params or {}
    label = params.get("source_csv_label")
    if isinstance(label, str):
        match = _TRAILING_NUMBER.search(label)
        if match:
            return int(match.group(1))
    stage = params.get("stage_label")
    try:
        return int(str(stage).strip())
    except (TypeError, ValueError):
        return None


def _file_named(files: Optional[list], file_type: str) -> tuple:
    """``(action_uuid, file_name)`` of the first file of *file_type*."""
    for entry in files or []:
        if (entry or {}).get("file_type") == file_type:
            return str(entry.get("action_uuid") or ""), str(entry.get("file_name") or "")
    return "", ""


def record_from_process(
    item: Optional[dict], sequences: Optional[dict]
) -> Optional[CompositionRecord]:
    """Build a record from one search item, or ``None`` when it is unusable.

    Args:
        item: One element of a `/api/search` PROCESS response.
        sequences: ``sequence_uuid -> sequence item``, from the SEQUENCE search.

    Returns:
        CompositionRecord with an empty ``values``, or ``None`` when the item
        carries no sample number or no quantification file.
    """
    entry = item or {}
    params = entry.get("process_params") or {}
    sample_no = sample_no_from(params)
    if sample_no is None:
        return None
    quant_uuid, quant_name = _file_named(entry.get("files"), QUANT_FILE_TYPE)
    if not quant_uuid or not quant_name:
        return None
    spec_uuid, spec_name = _file_named(entry.get("files"), SPECTRUM_FILE_TYPE)
    sequence_uuid = str(entry.get("sequence_uuid") or "")
    sequence = ((sequences or {}).get(sequence_uuid)) or {}
    try:
        plate_id = int(params.get("plate_id"))
    except (TypeError, ValueError):
        plate_id = 0
    return CompositionRecord(
        plate_id=plate_id,
        sample_no=sample_no,
        global_label=str(params.get("source_csv_label") or ""),
        run_use=str(entry.get("run_use") or ""),
        sequence_uuid=sequence_uuid,
        sequence_timestamp=str(sequence.get("sequence_timestamp") or ""),
        process_uuid=str(entry.get("process_uuid") or ""),
        process_timestamp=str(entry.get("process_timestamp") or ""),
        quant_action_uuid=quant_uuid,
        quant_file_name=quant_name,
        spectrum_action_uuid=spec_uuid,
        spectrum_file_name=spec_name,
        values={},
    )


def with_values(record: CompositionRecord, quant: Optional[dict]) -> CompositionRecord:
    """Return *record* with the quantification payload folded into ``values``.

    A column shorter than the transition list is skipped rather than zipped:
    `global_sample_label` carries one entry for five transitions, and zipping
    would truncate every other unit to one value while nothing reported a
    fault.
    """
    payload = quant or {}
    transitions = [str(t) for t in (payload.get("transition") or [])]
    values: dict = {name: {} for name in transitions}
    for column, series in payload.items():
        if column in NON_NUMERIC_COLUMNS:
            continue
        if not isinstance(series, list) or len(series) != len(transitions):
            continue
        for name, value in zip(transitions, series):
            values[name][column] = None if value is None else float(value)
    return replace(record, values=values)


def transition_names(records: Optional[list]) -> list:
    """Every transition any record carries, sorted."""
    names: set = set()
    for record in records or []:
        names.update(record.values)
    return sorted(names)


def unit_names(records: Optional[list]) -> list:
    """Every unit any record carries, sorted."""
    names: set = set()
    for record in records or []:
        for per_unit in record.values.values():
            names.update(per_unit)
    return sorted(names)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async timeout 600 \
  /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_composition_model.py -v
```

Expected: PASS, 13 tests.

- [ ] **Step 5: Format and commit**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
/home/dan/miniforge3/envs/helao/bin/black \
  helao/ui/shared/composition/ helao/core/tests/test_composition_model.py
git status --short --branch
git add helao/ui/shared/composition/ helao/core/tests/test_composition_model.py
git commit -m "feat(ui): model an XRF process as a CompositionRecord

A PROCESS item from the metadata API carries everything the composition page
needs except two things, and both have a trap. The sequence timestamp is
present but null on every process, so it comes from a separate SEQUENCE search
and the record carries an empty string when that search found nothing. The
analysis values live in an HLO the item's files list names, and that payload
mixes per-transition measurements with per-file scalars the API returns as
one-element lists -- zipping those against five transitions would truncate
every real unit to one value silently, so a column whose length does not match
is skipped.

A null atomic_fraction stays None rather than becoming 0.0: an uncalibrated
transition has no atomic fraction, and a zero would plot as a measurement.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: The metadata-API client layer

**Files:**
- Create: `helao/ui/shared/composition/api.py`
- Test: `helao/core/tests/test_composition_api.py`

**Interfaces:**
- Consumes: `model.NON_NUMERIC_COLUMNS` is not needed here; nothing else.
- Produces:
  - `API_SPEC_URL: str`, `API_BASE: str`
  - `get_client()` → a cached `AsyncOpenAPIClient`
  - `reset_client()` → drops the cache (tests)
  - `async search_processes(client, plate_id: int, *, size: int = 500) -> list[dict]`
  - `async fetch_sequences(client, sequence_uuids: list[str]) -> dict[str, dict]`
  - `async fetch_quant(client, action_uuid: str, file_name: str) -> dict`
  - `async fetch_spectrum(client, action_uuid: str, file_name: str) -> dict`

- [ ] **Step 1: Write the failing test**

Create `helao/core/tests/test_composition_api.py`:

```python
# helao/core/tests/test_composition_api.py
"""The metadata-API layer, against a stub client. No test here hits the network.

The response shapes are transcribed from real calls against the production API
for plate 10244 on 2026-09-22.
"""

import asyncio

import pytest

from helao.ui.shared.composition import api


class StubClient:
    """Records calls and replays canned responses."""

    def __init__(self, search=None, raw=None, plottable=None, action=None):
        self.calls = []
        self._search = list(search or [])
        self._raw = raw or {}
        self._plottable = plottable or {}
        self._action = action or {"action_name": "run_XRF"}

    async def search(self, request_body=None, **kwargs):
        self.calls.append(("search", request_body))
        return self._search.pop(0)

    async def read_raw_data(self, request_body=None, **kwargs):
        self.calls.append(("read_raw_data", request_body))
        key = (request_body or {}).get("key")
        if key not in self._raw:
            raise RuntimeError(f"404 for {key}")
        return self._raw[key]

    async def read_plottable_data(self, request_body=None, **kwargs):
        self.calls.append(("read_plottable_data", request_body))
        return self._plottable

    async def read_action(self, action_uuid=None, **kwargs):
        self.calls.append(("read_action", action_uuid))
        return self._action


def run(coro):
    return asyncio.run(coro)


def test_search_processes_filters_on_the_numeric_plate_id() -> None:
    """Not on a source_csv_label prefix: the filter Operation enum has no
    `like`, and plate_id is an exact match that needs no label convention."""
    client = StubClient(search=[{"total": 1, "items": [{"process_uuid": "a"}]}])
    run(api.search_processes(client, 10244))
    _, body = client.calls[0]
    assert {
        "field": "process_params.plate_id",
        "operation": "eq",
        "value": 10244,
    } in body["filters"]
    assert {
        "field": "entity_type",
        "operation": "in",
        "value": ["PROCESS"],
    } in body["filters"]


def test_search_processes_pages_until_total() -> None:
    """A plate with more processes than one page must not silently truncate."""
    client = StubClient(
        search=[
            {"total": 3, "items": [{"process_uuid": "a"}, {"process_uuid": "b"}]},
            {"total": 3, "items": [{"process_uuid": "c"}]},
        ]
    )
    items = run(api.search_processes(client, 10244, size=2))
    assert [i["process_uuid"] for i in items] == ["a", "b", "c"]
    assert [body["page"] for _, body in client.calls] == [1, 2]


def test_search_processes_stops_on_an_empty_page() -> None:
    """A total the server cannot actually deliver must not spin forever."""
    client = StubClient(
        search=[
            {"total": 99, "items": [{"process_uuid": "a"}]},
            {"total": 99, "items": []},
        ]
    )
    items = run(api.search_processes(client, 10244, size=1))
    assert len(items) == 1


def test_fetch_sequences_keys_by_uuid() -> None:
    client = StubClient(
        search=[
            {
                "total": 1,
                "items": [
                    {"sequence_uuid": "u1", "sequence_timestamp": "2026-08-13T11:54:21"}
                ],
            }
        ]
    )
    out = run(api.fetch_sequences(client, ["u1"]))
    assert out["u1"]["sequence_timestamp"] == "2026-08-13T11:54:21"


def test_fetch_sequences_on_an_empty_list_makes_no_request() -> None:
    client = StubClient()
    assert run(api.fetch_sequences(client, [])) == {}
    assert client.calls == []


def test_fetch_quant_derives_the_s3_key() -> None:
    """One request per process rather than two. The metadata endpoint returns
    exactly this key, verified against the production API."""
    client = StubClient(
        raw={"raw_data/act-1/quant.hlo.json": {"data": {"data": {"transition": ["Co.K"]}}}}
    )
    out = run(api.fetch_quant(client, "act-1", "quant.hlo.json"))
    assert out["transition"] == ["Co.K"]
    assert client.calls[0][1] == {"key": "raw_data/act-1/quant.hlo.json"}


def test_fetch_quant_falls_back_to_the_metadata_endpoint(monkeypatch) -> None:
    """OpenAPIClient cannot reach POST /api/file/metadata -- its name collides
    with the output-file GET and the GET wins -- so the fallback is httpx."""
    client = StubClient(raw={"other/key.json": {"data": {"data": {"transition": ["Y.K"]}}}})

    async def fake_lookup(action_uuid, file_name):
        assert (action_uuid, file_name) == ("act-1", "quant.hlo.json")
        return "other/key.json"

    monkeypatch.setattr(api, "_lookup_key", fake_lookup)
    out = run(api.fetch_quant(client, "act-1", "quant.hlo.json"))
    assert out["transition"] == ["Y.K"]


def test_fetch_spectrum_asks_the_action_for_its_name() -> None:
    """action_name is required by /file/plottable-data and is not on the
    process record."""
    client = StubClient(
        plottable={"plot_type": "line", "data": {"series": {"ev": [0, 10], "intensity": [1.0, 2.0]}}},
        action={"action_name": "run_XRF"},
    )
    out = run(api.fetch_spectrum(client, "act-1", "spec.hlo.json"))
    assert out["ev"] == [0, 10]
    assert ("read_action", "act-1") in client.calls
    _, body = [c for c in client.calls if c[0] == "read_plottable_data"][0]
    assert body["action_name"] == "run_XRF"
    assert body["file_type"] == "xrfspec_helao__json_file"


def test_fetch_spectrum_on_a_response_with_no_series() -> None:
    client = StubClient(plottable={"plot_type": "table", "data": None})
    assert run(api.fetch_spectrum(client, "act-1", "spec.hlo.json")) == {}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async timeout 600 \
  /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_composition_api.py -v
```

Expected: `ImportError: cannot import name 'api'`.

- [ ] **Step 3: Write the implementation**

Create `helao/ui/shared/composition/api.py`:

```python
# helao/ui/shared/composition/api.py
"""The HELAO metadata-API calls the composition page makes.

Every call here is unauthenticated HTTP against the public metadata API. The
platemap is the one thing this module does not fetch -- it needs S3 credentials
and comes from `helao.ui.shared.platemap` instead.

**The client is built lazily.** `AsyncOpenAPIClient` fetches the OpenAPI spec
*synchronously in its constructor*, so building one at import would put a
network round-trip in the import graph of every module that imports this one.
"""

from __future__ import annotations

import asyncio
import threading

import httpx

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: The metadata API's OpenAPI document.
API_SPEC_URL = "https://helao-api.caltech-hte.modelyst.com/api/openapi.json"

#: The metadata API root. Used only by :func:`_lookup_key`, which cannot go
#: through the client; see that function.
API_BASE = "https://helao-api.caltech-hte.modelyst.com/api"

#: The spectrum HLO's file_type, required by /api/file/plottable-data.
SPECTRUM_FILE_TYPE = "xrfspec_helao__json_file"

#: Request timeout for the one call that bypasses the client, in seconds.
_TIMEOUT_S = 30

_CLIENT = None
_CLIENT_LOCK = threading.Lock()


def get_client():
    """The shared async metadata-API client, built on first use.

    Returns:
        AsyncOpenAPIClient: bound to `search`, `read_raw_data`,
        `read_plottable_data` and `read_action`, among others.
    """
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            from helao.helpers.openapi_client import AsyncOpenAPIClient

            _CLIENT = AsyncOpenAPIClient(API_SPEC_URL)
        return _CLIENT


def reset_client() -> None:
    """Drop the cached client. For tests and for a credentials change."""
    global _CLIENT
    with _CLIENT_LOCK:
        _CLIENT = None


async def search_processes(client, plate_id: int, *, size: int = 500) -> list:
    """Every XRF process recorded for *plate_id*.

    Filters on the numeric ``process_params.plate_id`` rather than on a
    ``source_csv_label`` prefix: the filter ``Operation`` enum is exactly
    ``gte``/``lte``/``eq``/``match``/``contains``/``in``, with no ``like``, so a
    label prefix would be a ``contains`` heuristic over a string convention.
    ``plate_id`` is exact.

    Pages until the reported ``total`` is reached. A page that comes back empty
    ends the loop regardless, so a ``total`` the server cannot deliver does not
    spin.
    """
    items: list = []
    page = 1
    while True:
        body = {
            "size": size,
            "page": page,
            "match_keys": True,
            "filters": [
                {
                    "field": "process_params.plate_id",
                    "operation": "eq",
                    "value": int(plate_id),
                },
                {"field": "entity_type", "operation": "in", "value": ["PROCESS"]},
            ],
        }
        response = await client.search(request_body=body)
        batch = (response or {}).get("items") or []
        items.extend(batch)
        total = int((response or {}).get("total") or 0)
        if not batch or len(items) >= total:
            return items
        page += 1


async def fetch_sequences(client, sequence_uuids: list) -> dict:
    """The SEQUENCE records for *sequence_uuids*, keyed by uuid.

    A separate request because a PROCESS record's ``sequence_timestamp`` is
    present and null; the timestamp is the only thing distinguishing two
    sequences that share a name and a label.
    """
    uuids = [u for u in (sequence_uuids or []) if u]
    if not uuids:
        return {}
    body = {
        "size": max(len(uuids), 1),
        "page": 1,
        "match_keys": True,
        "filters": [
            {"field": "sequence_uuid", "operation": "in", "value": uuids},
            {"field": "entity_type", "operation": "in", "value": ["SEQUENCE"]},
        ],
    }
    response = await client.search(request_body=body)
    return {
        str(item.get("sequence_uuid")): item
        for item in ((response or {}).get("items") or [])
        if item.get("sequence_uuid")
    }


async def _lookup_key(action_uuid: str, file_name: str) -> str:
    """The S3 key of one action file, via ``POST /api/file/metadata``.

    **Not through the client, deliberately.** ``OpenAPIClient`` derives a
    method name from each operation's ``summary`` and silently overwrites a
    collision: this operation and ``GET /api/output-file/metadata`` are both
    summarised "Read Metadata", and the GET one wins, so ``read_metadata``
    takes a ``file_path`` query parameter and cannot reach this endpoint at
    all. Do not "simplify" this back into the client without fixing that
    derivation first.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
        response = await client.post(
            f"{API_BASE}/file/metadata",
            json={"file_name": file_name, "action_uuid": action_uuid},
        )
    response.raise_for_status()
    return str((response.json() or {}).get("file_name") or "")


async def fetch_quant(client, action_uuid: str, file_name: str) -> dict:
    """The quantification HLO's data columns for one action.

    The S3 key is derived rather than looked up -- ``/api/file/metadata``
    returns exactly ``raw_data/<action_uuid>/<file_name>``, verified against
    the production API -- which halves a plate load from two requests per
    process to one. The lookup is the fallback for a record stored under a
    different convention.
    """
    key = f"raw_data/{action_uuid}/{file_name}"
    try:
        response = await client.read_raw_data(request_body={"key": key})
    except Exception:
        key = await _lookup_key(action_uuid, file_name)
        if not key:
            return {}
        response = await client.read_raw_data(request_body={"key": key})
    return ((response or {}).get("data") or {}).get("data") or {}


async def fetch_spectrum(client, action_uuid: str, file_name: str) -> dict:
    """The spectrum series for one action: ``ev``, ``intensity``, ``channel``.

    ``/api/file/plottable-data`` requires an ``action_name``, which a PROCESS
    record does not carry, so the action is read first. That is one extra
    request per *clicked point*, not per process.
    """
    action = await client.read_action(action_uuid=action_uuid)
    body = {
        "file_name": file_name,
        "file_type": SPECTRUM_FILE_TYPE,
        "action_name": str((action or {}).get("action_name") or ""),
        "action_uuid": action_uuid,
    }
    response = await client.read_plottable_data(request_body=body)
    return ((response or {}).get("data") or {}).get("series") or {}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async timeout 600 \
  /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_composition_api.py -v
```

Expected: PASS, 9 tests.

- [ ] **Step 5: Format and commit**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
/home/dan/miniforge3/envs/helao/bin/black \
  helao/ui/shared/composition/api.py helao/core/tests/test_composition_api.py
git status --short --branch
git add helao/ui/shared/composition/api.py helao/core/tests/test_composition_api.py
git commit -m "feat(ui): metadata-API layer for the composition page

Four calls, all unauthenticated HTTP. Three details are measured against the
production API rather than assumed. A plate is selected by the numeric
process_params.plate_id, because the filter Operation enum has no like and a
source_csv_label prefix would be a contains heuristic over a string convention.
Sequence timestamps need their own search, because a process carries that field
as null and two sequences on the probed plate share a name and a label two
months apart. And an analysis output's S3 key is derivable as
raw_data/<action_uuid>/<file_name>, which halves a plate load to one request
per process, with the metadata lookup kept as the fallback.

That lookup cannot go through OpenAPIClient: the client derives method names
from an operation summary and silently overwrites collisions, so read_metadata
binds to the output-file GET and POST /api/file/metadata is unreachable. The
httpx call carries a comment saying so, because it reads like something to
simplify away.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Grouping by run_use and by sequence

**Files:**
- Create: `helao/ui/shared/composition/grouping.py`
- Test: `helao/core/tests/test_composition_grouping.py`

**Interfaces:**
- Consumes: `model.CompositionRecord` from Task 2.
- Produces:
  - `ALL: str` — the "no filter" option label, `"All"`
  - `NO_RUN_USE: str` — `"(no run_use)"`
  - `run_use_options(records) -> list[str]` — `ALL` first
  - `sequence_label(record) -> str`
  - `sequence_options(records) -> list[str]` — `ALL` first, newest first
  - `filter_records(records, *, run_use: str, sequence: str) -> list`

- [ ] **Step 1: Write the failing test**

Create `helao/core/tests/test_composition_grouping.py`:

```python
# helao/core/tests/test_composition_grouping.py
"""The two grouping dropdowns.

The sequence label carries the timestamp because the probed plate has two
sequences with the same name and the same label two months apart -- the name
would render them identical.
"""

import pytest

from helao.ui.shared.composition import grouping
from helao.ui.shared.composition.model import CompositionRecord


def record(**kwargs) -> CompositionRecord:
    base = dict(
        plate_id=10244,
        sample_no=1,
        global_label="legacy__solid__10244_1",
        run_use="post_anneal",
        sequence_uuid="06a7e382-a773-731d-8000-d7e3e21eacec",
        sequence_timestamp="2026-08-13T11:54:21.000000",
        process_uuid="p",
        process_timestamp="2026-08-13T11:57:41.000000",
        quant_action_uuid="a",
        quant_file_name="q.json",
        spectrum_action_uuid="a",
        spectrum_file_name="s.json",
        values={},
    )
    base.update(kwargs)
    return CompositionRecord(**base)


OLD = record()
NEW = record(
    sequence_uuid="07528a44-2e9b-56dc-a3c1-912f6f018865",
    sequence_timestamp="2026-09-10T17:02:37.000000",
    run_use="pre_anneal",
    sample_no=2,
)


def test_sequence_label_carries_the_timestamp() -> None:
    assert grouping.sequence_label(OLD) == "2026-08-13T11:54:21.000000 · 06a7e382"


def test_two_sequences_sharing_a_name_get_distinct_labels() -> None:
    assert grouping.sequence_label(OLD) != grouping.sequence_label(NEW)


def test_sequence_label_falls_back_to_the_bare_uuid() -> None:
    assert grouping.sequence_label(record(sequence_timestamp="")) == (
        "06a7e382-a773-731d-8000-d7e3e21eacec"
    )


def test_sequence_options_are_newest_first_after_all() -> None:
    options = grouping.sequence_options([OLD, NEW])
    assert options[0] == grouping.ALL
    assert options[1] == grouping.sequence_label(NEW)
    assert options[2] == grouping.sequence_label(OLD)


def test_run_use_options_start_with_all() -> None:
    assert grouping.run_use_options([OLD, NEW]) == [
        grouping.ALL,
        "post_anneal",
        "pre_anneal",
    ]


def test_an_empty_run_use_is_named_not_blank() -> None:
    """A blank dropdown entry reads as a rendering failure."""
    options = grouping.run_use_options([record(run_use="")])
    assert options == [grouping.ALL, grouping.NO_RUN_USE]


def test_filter_on_all_returns_everything() -> None:
    kept = grouping.filter_records(
        [OLD, NEW], run_use=grouping.ALL, sequence=grouping.ALL
    )
    assert kept == [OLD, NEW]


def test_the_two_filters_compose() -> None:
    kept = grouping.filter_records(
        [OLD, NEW], run_use="pre_anneal", sequence=grouping.sequence_label(NEW)
    )
    assert kept == [NEW]


def test_a_composition_that_matches_nothing_returns_empty() -> None:
    kept = grouping.filter_records(
        [OLD, NEW], run_use="pre_anneal", sequence=grouping.sequence_label(OLD)
    )
    assert kept == []


def test_filter_matches_the_named_empty_run_use() -> None:
    blank = record(run_use="")
    kept = grouping.filter_records(
        [blank, OLD], run_use=grouping.NO_RUN_USE, sequence=grouping.ALL
    )
    assert kept == [blank]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async timeout 600 \
  /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_composition_grouping.py -v
```

Expected: `ImportError: cannot import name 'grouping'`.

- [ ] **Step 3: Write the implementation**

Create `helao/ui/shared/composition/grouping.py`:

```python
# helao/ui/shared/composition/grouping.py
"""The composition page's two grouping dropdowns.

Both are plain string selections so they can ride a Reflex var directly, and
both compose: picking a run_use and a sequence intersects.
"""

from __future__ import annotations

#: The "no filter" entry, first in every option list.
ALL = "All"

#: Stands in for an empty ``run_use``. A blank dropdown entry reads as a
#: rendering failure rather than as a record with no run_use.
NO_RUN_USE = "(no run_use)"


def run_use_options(records) -> list:
    """Every ``run_use`` present, sorted, with :data:`ALL` first."""
    seen = {record.run_use or NO_RUN_USE for record in records or []}
    return [ALL] + sorted(seen)


def sequence_label(record) -> str:
    """One sequence's dropdown label.

    The timestamp leads because it is the only thing that distinguishes two
    sequences sharing a name and a label -- which the probed plate has, two
    months apart. The uuid's first field disambiguates two runs in one second.
    """
    if not record.sequence_timestamp:
        return record.sequence_uuid
    head = record.sequence_uuid.split("-")[0] if record.sequence_uuid else ""
    return f"{record.sequence_timestamp} · {head}" if head else record.sequence_timestamp


def sequence_options(records) -> list:
    """Every sequence present, newest first, with :data:`ALL` first."""
    by_label: dict = {}
    for record in records or []:
        by_label.setdefault(sequence_label(record), record.sequence_timestamp)
    ordered = sorted(by_label, key=lambda label: by_label[label], reverse=True)
    return [ALL] + ordered


def filter_records(records, *, run_use: str, sequence: str) -> list:
    """The records matching both selections.

    Args:
        records: Every retrieved record.
        run_use: A :func:`run_use_options` entry.
        sequence: A :func:`sequence_options` entry.
    """
    kept = []
    for record in records or []:
        own_run_use = record.run_use or NO_RUN_USE
        if run_use != ALL and own_run_use != run_use:
            continue
        if sequence != ALL and sequence_label(record) != sequence:
            continue
        kept.append(record)
    return kept
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async timeout 600 \
  /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_composition_grouping.py -v
```

Expected: PASS, 10 tests.

- [ ] **Step 5: Format and commit**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
/home/dan/miniforge3/envs/helao/bin/black \
  helao/ui/shared/composition/grouping.py \
  helao/core/tests/test_composition_grouping.py
git status --short --branch
git add helao/ui/shared/composition/grouping.py \
  helao/core/tests/test_composition_grouping.py
git commit -m "feat(ui): group composition records by run_use and by sequence

The sequence label leads with the timestamp rather than the name because the
probed plate carries two sequences named XRFS_noStandards and labelled
CoYPt-102441, two months apart; by name they render identical. An empty run_use
becomes a named entry rather than a blank one, which reads as a rendering
failure. Both filters compose.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Ternary geometry

**Files:**
- Create: `helao/ui/shared/composition/ternary.py`
- Test: `helao/core/tests/test_composition_ternary.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `VERTICES: tuple[tuple[float, float], ...]` — three `(x, y)` pairs
  - `barycentric_to_cartesian(a, b, c) -> tuple[np.ndarray, np.ndarray, np.ndarray]`
    returning `(xs, ys, keep)` where `keep` is a boolean mask over the input
  - `triangle_edges() -> tuple[np.ndarray, np.ndarray]`

- [ ] **Step 1: Write the failing test**

Create `helao/core/tests/test_composition_ternary.py`:

```python
# helao/core/tests/test_composition_ternary.py
"""Barycentric-to-cartesian for the ternary diagram."""

import math

import numpy as np
import pytest

from helao.ui.shared.composition import ternary


def test_a_pure_first_component_lands_on_the_first_vertex() -> None:
    xs, ys, keep = ternary.barycentric_to_cartesian([1.0], [0.0], [0.0])
    assert keep.tolist() == [True]
    assert xs[0] == pytest.approx(ternary.VERTICES[0][0])
    assert ys[0] == pytest.approx(ternary.VERTICES[0][1])


def test_a_pure_third_component_lands_on_the_apex() -> None:
    xs, ys, _ = ternary.barycentric_to_cartesian([0.0], [0.0], [1.0])
    assert xs[0] == pytest.approx(0.5)
    assert ys[0] == pytest.approx(math.sqrt(3) / 2)


def test_an_equal_mixture_lands_at_the_centroid() -> None:
    xs, ys, _ = ternary.barycentric_to_cartesian([1.0], [1.0], [1.0])
    assert xs[0] == pytest.approx(0.5)
    assert ys[0] == pytest.approx(math.sqrt(3) / 6)


def test_an_unnormalised_triple_is_normalised() -> None:
    """Raw nanomoles do not sum to 1. Normalising is what makes any unit
    plottable on a ternary diagram, not just atomic fractions."""
    one = ternary.barycentric_to_cartesian([2.0], [2.0], [2.0])
    two = ternary.barycentric_to_cartesian([1.0], [1.0], [1.0])
    assert one[0][0] == pytest.approx(two[0][0])
    assert one[1][0] == pytest.approx(two[1][0])


def test_a_zero_sum_point_is_dropped() -> None:
    _, _, keep = ternary.barycentric_to_cartesian([0.0], [0.0], [0.0])
    assert keep.tolist() == [False]


def test_a_nan_point_is_dropped() -> None:
    """An uncalibrated transition arrives as None and becomes NaN. Plotting it
    reaches the renderer as a coordinate and blanks the chart."""
    _, _, keep = ternary.barycentric_to_cartesian(
        [1.0, float("nan")], [1.0, 1.0], [1.0, 1.0]
    )
    assert keep.tolist() == [True, False]


def test_a_negative_component_is_dropped() -> None:
    """A negative fit residual is not a composition."""
    _, _, keep = ternary.barycentric_to_cartesian([-1.0], [1.0], [1.0])
    assert keep.tolist() == [False]


def test_dropped_points_are_removed_from_the_outputs() -> None:
    xs, ys, keep = ternary.barycentric_to_cartesian(
        [1.0, 0.0], [0.0, 0.0], [0.0, 0.0]
    )
    assert len(xs) == len(ys) == 1
    assert keep.tolist() == [True, False]


def test_mismatched_lengths_raise() -> None:
    """A caller bug, not something to paper over by truncating."""
    with pytest.raises(ValueError):
        ternary.barycentric_to_cartesian([1.0, 1.0], [1.0], [1.0])


def test_triangle_edges_close_the_triangle() -> None:
    xs, ys = ternary.triangle_edges()
    assert len(xs) == len(ys) == 4
    assert (xs[0], ys[0]) == (xs[-1], ys[-1])
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async timeout 600 \
  /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_composition_ternary.py -v
```

Expected: `ImportError: cannot import name 'ternary'`.

- [ ] **Step 3: Write the implementation**

Create `helao/ui/shared/composition/ternary.py`:

```python
# helao/ui/shared/composition/ternary.py
"""Barycentric-to-cartesian for the ternary diagram.

xy 0.0.5 ships no ternary mark, so the diagram is a scatter in a transformed
plane plus three line segments for the edges. Keeping the transform here, away
from any xy import, is what makes it testable with plain arrays.
"""

from __future__ import annotations

import math

import numpy as np

#: The unit triangle, apex at the top: first component bottom-left, second
#: bottom-right, third at the apex.
VERTICES = ((0.0, 0.0), (1.0, 0.0), (0.5, math.sqrt(3) / 2))


def barycentric_to_cartesian(a, b, c) -> tuple:
    """Project three components onto the unit triangle.

    The triple is normalised to sum to 1 per point, which is what lets any unit
    be plotted here and not only ``atomic_fraction``: raw nanomoles carry a
    magnitude a ternary diagram has no axis for.

    A point is dropped when any component is non-finite (an uncalibrated
    transition arrives as ``None`` and becomes NaN), when any component is
    negative (a negative fit residual is not a composition), or when the three
    sum to zero (no direction to project).

    Args:
        a: First component, one value per point.
        b: Second component.
        c: Third component.

    Returns:
        tuple: ``(xs, ys, keep)``. ``xs``/``ys`` hold only the kept points;
        ``keep`` is a boolean mask over the *input*, so a caller can filter its
        own parallel arrays with it.

    Raises:
        ValueError: If the three inputs differ in length.
    """
    arrays = [np.asarray(v, dtype=float).ravel() for v in (a, b, c)]
    if len({arr.size for arr in arrays}) != 1:
        raise ValueError(
            "a, b and c must be the same length, got "
            f"{[int(arr.size) for arr in arrays]}"
        )
    stacked = np.vstack(arrays)
    totals = stacked.sum(axis=0)
    keep = (
        np.isfinite(stacked).all(axis=0)
        & (stacked >= 0).all(axis=0)
        & np.isfinite(totals)
        & (totals > 0)
    )
    if not keep.any():
        return np.array([]), np.array([]), keep
    kept = stacked[:, keep] / totals[keep]
    xs = (
        kept[0] * VERTICES[0][0]
        + kept[1] * VERTICES[1][0]
        + kept[2] * VERTICES[2][0]
    )
    ys = (
        kept[0] * VERTICES[0][1]
        + kept[1] * VERTICES[1][1]
        + kept[2] * VERTICES[2][1]
    )
    return xs, ys, keep


def triangle_edges() -> tuple:
    """The triangle outline as one closed polyline: ``(xs, ys)``, 4 points."""
    xs = np.array([v[0] for v in VERTICES] + [VERTICES[0][0]], dtype=float)
    ys = np.array([v[1] for v in VERTICES] + [VERTICES[0][1]], dtype=float)
    return xs, ys
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async timeout 600 \
  /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_composition_ternary.py -v
```

Expected: PASS, 10 tests.

- [ ] **Step 5: Format and commit**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
/home/dan/miniforge3/envs/helao/bin/black \
  helao/ui/shared/composition/ternary.py \
  helao/core/tests/test_composition_ternary.py
git status --short --branch
git add helao/ui/shared/composition/ternary.py \
  helao/core/tests/test_composition_ternary.py
git commit -m "feat(ui): barycentric projection for the ternary diagram

Normalising per point is what lets any unit be plotted, not only
atomic_fraction: raw nanomoles carry a magnitude a ternary diagram has no axis
for. The mask is returned alongside the coordinates rather than applied
silently, so a caller can filter its own parallel arrays with it -- dropping
points independently is how colours end up on the wrong markers.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: RBF interpolation over the platemap

**Files:**
- Create: `helao/ui/shared/composition/interp.py`
- Test: `helao/core/tests/test_composition_interp.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `MIN_POINTS: int` — 4
  - `rbf_surface(xs, ys, values, target_xs, target_ys, *, kernel="thin_plate_spline") -> np.ndarray`

- [ ] **Step 1: Write the failing test**

Create `helao/core/tests/test_composition_interp.py`:

```python
# helao/core/tests/test_composition_interp.py
"""The RBF surface behind the plate-map toggle."""

import numpy as np
import pytest

from helao.ui.shared.composition import interp


GRID_X = [0.0, 1.0, 0.0, 1.0, 0.5]
GRID_Y = [0.0, 0.0, 1.0, 1.0, 0.5]


def test_a_plane_is_reproduced_at_an_unmeasured_position() -> None:
    """value = 2x + 3y. An RBF fit on a plane must return the plane."""
    values = [2 * x + 3 * y for x, y in zip(GRID_X, GRID_Y)]
    out = interp.rbf_surface(GRID_X, GRID_Y, values, [0.25], [0.75])
    assert out[0] == pytest.approx(2 * 0.25 + 3 * 0.75, abs=1e-6)


def test_measured_positions_come_back_unchanged() -> None:
    values = [2 * x + 3 * y for x, y in zip(GRID_X, GRID_Y)]
    out = interp.rbf_surface(GRID_X, GRID_Y, values, GRID_X, GRID_Y)
    assert out == pytest.approx(values, abs=1e-6)


def test_too_few_points_returns_empty() -> None:
    """Three points cannot support a surface, and the toggle says so rather
    than drawing one."""
    out = interp.rbf_surface([0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [1.0, 2.0, 3.0], [0.5], [0.5])
    assert out.size == 0


def test_duplicate_coordinates_are_collapsed_not_raised() -> None:
    """RBFInterpolator raises on a singular matrix. Two measurements of one
    position is normal -- pre_anneal and post_anneal sit on the same sample."""
    xs = GRID_X + [0.0]
    ys = GRID_Y + [0.0]
    values = [2 * x + 3 * y for x, y in zip(GRID_X, GRID_Y)] + [10.0]
    out = interp.rbf_surface(xs, ys, values, [0.0], [0.0])
    assert out.size == 1
    assert out[0] == pytest.approx(5.0, abs=1e-6)


def test_non_finite_measurements_are_dropped_before_fitting() -> None:
    xs = GRID_X + [2.0]
    ys = GRID_Y + [2.0]
    values = [2 * x + 3 * y for x, y in zip(GRID_X, GRID_Y)] + [float("nan")]
    out = interp.rbf_surface(xs, ys, values, [0.25], [0.75])
    assert out[0] == pytest.approx(2 * 0.25 + 3 * 0.75, abs=1e-6)


def test_dropping_non_finite_can_fall_below_the_minimum() -> None:
    xs = [0.0, 1.0, 0.0, 1.0]
    ys = [0.0, 0.0, 1.0, 1.0]
    values = [1.0, float("nan"), float("nan"), 2.0]
    assert interp.rbf_surface(xs, ys, values, [0.5], [0.5]).size == 0


def test_no_targets_returns_empty() -> None:
    values = [2 * x + 3 * y for x, y in zip(GRID_X, GRID_Y)]
    assert interp.rbf_surface(GRID_X, GRID_Y, values, [], []).size == 0


def test_mismatched_input_lengths_raise() -> None:
    with pytest.raises(ValueError):
        interp.rbf_surface([0.0, 1.0], [0.0], [1.0, 2.0], [0.5], [0.5])
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async timeout 600 \
  /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_composition_interp.py -v
```

Expected: `ImportError: cannot import name 'interp'`.

- [ ] **Step 3: Write the implementation**

Create `helao/ui/shared/composition/interp.py`:

```python
# helao/ui/shared/composition/interp.py
"""Interpolate measured values across every platemap position.

The plate-map toggle's whole point is to show more points than were measured,
so the surface is evaluated at the platemap's positions rather than on a grid.
"""

from __future__ import annotations

import numpy as np

#: Below this many distinct measured points there is no surface to fit, and the
#: toggle reports that rather than drawing one.
MIN_POINTS = 4


def rbf_surface(
    xs,
    ys,
    values,
    target_xs,
    target_ys,
    *,
    kernel: str = "thin_plate_spline",
) -> np.ndarray:
    """Fit an RBF to the measured points and evaluate it at the targets.

    Two guards, both for failures `RBFInterpolator` reports as an exception
    from inside a render:

    * Points whose coordinate or value is non-finite are dropped first. An
      uncalibrated transition arrives as ``None`` and becomes NaN.
    * Duplicated coordinates are collapsed to their mean. Two measurements of
      one position is normal here -- a pre-anneal and a post-anneal process sit
      on the same sample -- and a repeated coordinate makes the system singular.

    Args:
        xs: Measured x coordinates.
        ys: Measured y coordinates.
        values: Measured values, one per point.
        target_xs: Positions to evaluate at.
        target_ys: Positions to evaluate at.
        kernel: An `RBFInterpolator` kernel name.

    Returns:
        numpy.ndarray: One value per target, or an empty array when there are
        fewer than :data:`MIN_POINTS` usable points or no targets.

    Raises:
        ValueError: If ``xs``, ``ys`` and ``values`` differ in length, or if the
            two target arrays differ in length.
    """
    px = np.asarray(xs, dtype=float).ravel()
    py = np.asarray(ys, dtype=float).ravel()
    pv = np.asarray(values, dtype=float).ravel()
    if not (px.size == py.size == pv.size):
        raise ValueError(
            f"xs, ys and values must be the same length, got "
            f"{int(px.size)}, {int(py.size)}, {int(pv.size)}"
        )
    tx = np.asarray(target_xs, dtype=float).ravel()
    ty = np.asarray(target_ys, dtype=float).ravel()
    if tx.size != ty.size:
        raise ValueError(
            f"target_xs and target_ys must be the same length, got "
            f"{int(tx.size)}, {int(ty.size)}"
        )
    if tx.size == 0:
        return np.array([])

    keep = np.isfinite(px) & np.isfinite(py) & np.isfinite(pv)
    px, py, pv = px[keep], py[keep], pv[keep]
    if px.size == 0:
        return np.array([])

    points = np.column_stack([px, py])
    unique, inverse = np.unique(points, axis=0, return_inverse=True)
    if unique.shape[0] != points.shape[0]:
        summed = np.zeros(unique.shape[0], dtype=float)
        counts = np.zeros(unique.shape[0], dtype=float)
        np.add.at(summed, inverse, pv)
        np.add.at(counts, inverse, 1.0)
        pv = summed / counts
        points = unique

    if points.shape[0] < MIN_POINTS:
        return np.array([])

    from scipy.interpolate import RBFInterpolator

    interpolator = RBFInterpolator(points, pv, kernel=kernel)
    return np.asarray(interpolator(np.column_stack([tx, ty])), dtype=float)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async timeout 600 \
  /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_composition_interp.py -v
```

Expected: PASS, 8 tests.

- [ ] **Step 5: Format and commit**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
/home/dan/miniforge3/envs/helao/bin/black \
  helao/ui/shared/composition/interp.py \
  helao/core/tests/test_composition_interp.py
git status --short --branch
git add helao/ui/shared/composition/interp.py \
  helao/core/tests/test_composition_interp.py
git commit -m "feat(ui): RBF surface across every platemap position

Evaluated at the platemap's own positions rather than on a grid, because
showing more points than were measured is the toggle's whole point. Two guards
cover failures RBFInterpolator raises from inside a render: non-finite points
are dropped before fitting, and duplicated coordinates are collapsed to their
mean rather than left to make the system singular -- a pre-anneal and a
post-anneal measurement of one sample share a position, which is normal here.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: `plots.ternary`

**Files:**
- Modify: `helao/ui/reflex/plots.py` (`__all__` near line 13; append the function after `scatter_map`)
- Test: `helao/core/tests/test_reflex_plots.py`

**Interfaces:**
- Consumes: `helao.ui.shared.composition.ternary` from Task 5.
- Produces:
  - `plots.ternary(a, b, c, *, labels, values=None, panel_id="ternary", version=0) -> ChartPayload`

- [ ] **Step 1: Write the failing test**

Append to `helao/core/tests/test_reflex_plots.py`:

```python
def test_ternary_publishes_points_edges_and_vertex_labels() -> None:
    """Four traces and three annotations, not seven traces.

    `xy.text` returns an `Annotation`, not a `Mark`: it takes scalar x/y and a
    single `value` string, and `build_payload_split` puts it under `annotations`
    rather than `traces`. Verified against xy 0.0.5.
    """
    from helao.ui.reflex import plots

    payload = plots.ternary(
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
        labels=("Co.K", "Y.K", "Pt.L"),
        panel_id="tern-test",
        version=1,
    )
    assert payload.buffer_url.endswith("tern-test?v=1")
    assert len(payload.spec.get("traces") or []) == 4
    labels = [a.get("text") for a in payload.spec.get("annotations") or []]
    assert labels == ["Co.K", "Y.K", "Pt.L"]


def test_ternary_drops_a_point_whose_components_are_all_none() -> None:
    """An uncalibrated transition arrives as None. Plotted, it reaches the
    renderer as a coordinate and blanks the chart."""
    from helao.ui.reflex import plots

    payload = plots.ternary(
        [1.0, float("nan")],
        [1.0, 1.0],
        [1.0, 1.0],
        labels=("a", "b", "c"),
        panel_id="tern-nan",
        version=1,
    )
    assert payload.spec.get("traces")


def test_ternary_filters_values_with_the_same_mask() -> None:
    """Colour is per point. Filtering points and colours independently puts the
    wrong colour on the wrong marker."""
    from helao.ui.reflex import plots

    payload = plots.ternary(
        [1.0, 0.0],
        [0.0, 0.0],
        [0.0, 0.0],
        labels=("a", "b", "c"),
        values=[5.0, 6.0],
        panel_id="tern-mask",
        version=1,
    )
    assert payload.spec.get("traces")


def test_ternary_rejects_the_wrong_number_of_labels() -> None:
    from helao.ui.reflex import plots

    with pytest.raises(ValueError):
        plots.ternary([1.0], [1.0], [1.0], labels=("only", "two"))


def test_ternary_on_no_usable_points_still_draws_the_triangle() -> None:
    """An empty diagram with a visible triangle reads as "no data"; a blank
    canvas reads as a broken page."""
    from helao.ui.reflex import plots

    payload = plots.ternary(
        [0.0], [0.0], [0.0], labels=("a", "b", "c"), panel_id="tern-empty", version=1
    )
    assert len(payload.spec.get("traces") or []) == 3
    assert len(payload.spec.get("annotations") or []) == 3


def test_ternary_rejects_a_values_array_of_the_wrong_length() -> None:
    from helao.ui.reflex import plots

    with pytest.raises(ValueError):
        plots.ternary([1.0, 1.0], [1.0, 1.0], [1.0, 1.0], labels=("a", "b", "c"), values=[1.0])
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async timeout 600 \
  /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_reflex_plots.py -k ternary -v
```

Expected: FAIL, `AttributeError: module 'helao.ui.reflex.plots' has no attribute 'ternary'`.

- [ ] **Step 3: Write the implementation**

In `helao/ui/reflex/plots.py`, add `"ternary"` to `__all__`, add
`from helao.ui.shared.composition import ternary as _ternary` to the imports,
and append after `scatter_map`:

```python
def ternary(
    a,
    b,
    c,
    *,
    labels,
    values=None,
    panel_id: str = "ternary",
    version: int = 0,
):
    """Render a ternary diagram: three components on the unit triangle.

    xy 0.0.5 ships no ternary mark, so the diagram is assembled from
    primitives: one scatter in the transformed plane, three line segments for
    the edges, and three ``xy.text`` annotations for the vertex labels. Axis
    labels are left empty deliberately -- a ternary diagram has no meaningful x
    or y axis, and the vertex labels carry the identification instead.

    **``xy.text`` is an annotation, not a mark.** It takes scalar ``x``/``y``
    and one ``value`` string, has no ``name``, and lands under the spec's
    ``annotations`` rather than its ``traces``. So a rendered diagram with
    points carries 4 traces and 3 annotations, not 7 traces.

    Args:
        a: First component, one value per point.
        b: Second component.
        c: Third component.
        labels: Three vertex labels, in the order ``(a, b, c)``.
        values: Optional per-point scalar driving colour.
        panel_id: Stable panel identity for the buffer route.
        version: Monotonic data version.

    Returns:
        ChartPayload: Assign into the panel state vars bound by :func:`chart`.

    Raises:
        ValueError: If ``labels`` does not hold exactly three entries, or if
            the three component arrays differ in length.
    """
    names = tuple(labels or ())
    if len(names) != 3:
        raise ValueError(f"ternary needs exactly 3 vertex labels, got {len(names)}")
    xs, ys, keep = _ternary.barycentric_to_cartesian(a, b, c)
    marks = []
    if xs.size:
        mark_kwargs: dict[str, Any] = {"x": xs, "y": ys, "name": "samples"}
        if values is not None:
            # Masked with the same `keep` the coordinates were: colour is per
            # point, and filtering the two independently puts a colour on the
            # wrong marker.
            colors = _as_float_array(values)
            if colors.size != keep.size:
                raise ValueError(
                    f"values has length {colors.size}, expected {int(keep.size)}"
                )
            mark_kwargs["color"] = colors[keep]
        else:
            mark_kwargs["color"] = PALETTE[0]
        marks.append(xy.scatter(**mark_kwargs))
    # The outline is drawn as three separate segments rather than one closed
    # polyline so each edge is its own trace, which keeps `layout_token` stable
    # when the point count changes but the frame does not.
    edge_xs, edge_ys = _ternary.triangle_edges()
    edge_color = CHART_CHROME["--chart-axis"]
    for index in range(3):
        marks.append(
            xy.line(
                x=np.array([edge_xs[index], edge_xs[index + 1]]),
                y=np.array([edge_ys[index], edge_ys[index + 1]]),
                name=f"edge_{index}",
                color=edge_color,
            )
        )
    for (vx, vy), name in zip(_ternary.VERTICES, names):
        # Scalars and a single string: `xy.text` is an Annotation constructor,
        # not a Mark one. Passed as a chart child alongside the marks, it lands
        # in the spec's `annotations`.
        marks.append(xy.text(float(vx), float(vy), str(name), color=edge_color))
    figure = _chart(marks, _axes("", "", False))
    return _publish(figure, panel_id, version)
```

`CHART_CHROME` is keyed by CSS custom-property name, so the axis colour is
`CHART_CHROME["--chart-axis"]` (`#94a3b8`) — not `CHART_CHROME["axis"]`. Add
`CHART_CHROME` to the existing
`from helao.ui.shared.palette import SERIES` line in `plots.py`. Do not write a
hex literal; the AST sweep in `test_palette.py` rejects one.

- [ ] **Step 4: Run the tests**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
export PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async
P=/home/dan/miniforge3/envs/helao/bin/python
timeout 600 $P -m pytest helao/core/tests/test_reflex_plots.py -v
timeout 600 $P -m pytest helao/core/tests/test_palette.py -q
```

Expected: both PASS. The two xy signatures this task depends on were verified
against xy 0.0.5 while the plan was written:

```
xy.text(x: CoordinateLike, y: CoordinateLike, value: str, *, dx=6.0, dy=-6.0,
        color=None, anchor='start', class_name=None, style=None) -> Annotation
xy.line(x=None, y=None, *, data=None, name=None, color=None, width=1.5, ...) -> Mark
```

Add both, and the traces-versus-annotations split, to
`docs/superpowers/notes/2026-08-01-xy-api-probe.md` — that note is where this
repo keeps xy's verified call signatures, and it is meant to be re-checked
after any version bump.

- [ ] **Step 5: Format and commit**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
/home/dan/miniforge3/envs/helao/bin/black \
  helao/ui/reflex/plots.py helao/core/tests/test_reflex_plots.py
git status --short --branch
git add helao/ui/reflex/plots.py helao/core/tests/test_reflex_plots.py \
  docs/superpowers/notes/2026-08-01-xy-api-probe.md
git commit -m "feat(ui): a ternary mark for the plot facade

xy 0.0.5 ships no ternary mark -- polar_chart and radar_chart are a different
projection -- so the diagram is one scatter in the transformed plane plus three
line segments and three text annotations -- xy.text is an Annotation
constructor taking scalars and one string, so the vertex labels land under the
spec's annotations rather than its traces. The edges are separate traces rather than
one closed polyline so the layout token stays stable when only the point count
changes, and the colour array is masked with the same keep the coordinates
were, because filtering points and colours independently puts a colour on the
wrong marker. Axis labels stay empty: a ternary diagram has no meaningful x or
y axis.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: The `/composition` page tint

**Files:**
- Modify: `helao/ui/shared/palette.py` (`TW` near line 60; `REFLEX_PAGE_TINTS` at 181)
- Modify: `helao/core/tests/test_palette.py` (`PAGE_TINT_TEXT_ROWS` at 564; `SLATE_500_ON_TINT_ROWS` at 583; the test at 879)
- Test: `helao/core/tests/test_palette.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `REFLEX_PAGE_TINTS["/composition"] == "lime-50"`, `TW["lime-50"]`.

This task adds the tint *before* the route exists, so `test_reflex_page_tints_cover_the_shell_routes` will fail until Task 10 adds `/composition` to `SHELL_ROUTES`. That is deliberate: the tint's measurements belong in their own reviewable change, and the failing assertion is the reminder that the pair is incomplete. Run the rest of `test_palette.py` and expect exactly that one failure.

- [ ] **Step 1: Add the measured rows to the test file**

In `helao/core/tests/test_palette.py`, add to `PAGE_TINT_TEXT_ROWS`:

```python
    ("slate-900", "lime-50"): 17.25,  # /composition
    ("slate-600", "lime-50"): 7.32,
```

and to `SLATE_500_ON_TINT_ROWS`:

```python
    ("slate-500", "lime-50"): 4.60,
```

Rename `test_slate_500_fails_the_body_floor_on_three_of_the_six_tints` to
`test_slate_500_fails_the_body_floor_on_three_of_the_seven_tints`, leaving its
asserted set `{"sky-50", "violet-50", "rose-50"}` unchanged, and extend its
docstring's last sentence:

```python
    """Exactly three, and named -- not "at least one".

    A count would pass if the failing set moved to three different tints, and
    the point of the row block above is that *which* surfaces fail is not
    guessable from the shade names. ``rose-50`` joined them when ``/control``
    was added, at 4.33: a sixth route was not going to make the case for
    ``slate-500`` any better, and it did not. ``lime-50`` arrived with
    ``/composition`` at 4.60 and did not join them, which is the other half of
    the same point -- the set is measured, not predicted.
    """
```

- [ ] **Step 2: Run the palette tests to verify they fail**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async timeout 600 \
  /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_palette.py -v
```

Expected: failures naming `lime-50` as missing from `TW`, and
`test_page_tint_rows_cover_every_route_twice` failing because the declared rows
now exceed the declared tints.

- [ ] **Step 3: Add the shade and the tint**

In `helao/ui/shared/palette.py`, add to `TW`, in family order (after the
`green-*` entries and before `emerald-50`):

```python
    "lime-50": "#f7fee7",
```

and to `REFLEX_PAGE_TINTS`:

```python
    "/composition": "lime-50",
```

Extend the `REFLEX_PAGE_TINTS` docstring with the reason for this shade:

```
``lime-50`` was chosen by measurement, not by taste. Of the four unused
50-level candidates it is the only one both further from its nearest existing
tint (ΔE 5.30 to ``amber-50``) than the existing tints are from each other
(their minimum pairwise ΔE is 3.21), and leaving every table border's weakest
surface unchanged. ``indigo-50`` fails both: ΔE 2.25 to ``violet-50``, and it
becomes the worst surface for all five borders.
```

- [ ] **Step 4: Run the palette tests**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async timeout 600 \
  /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_palette.py -v
```

Expected: exactly one failure,
`test_reflex_page_tints_cover_the_shell_routes`, because `/composition` is not
yet a shell route. Every other test passes, including
`test_page_tint_text_contrast[('slate-600', 'lime-50')]`,
`test_slate_600_clears_every_tint_by_a_real_margin` and
`test_border_rows_cover_every_hue_at_its_worst_tint`. If any *other* test fails,
the measured numbers are wrong — recompute them rather than adjusting the
assertion:

```bash
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async \
/home/dan/miniforge3/envs/helao/bin/python -c "
from helao.core.tests.test_palette import contrast_ratio, TW
for fg in ('slate-900','slate-600','slate-500'):
    print(fg, round(contrast_ratio(TW[fg], TW['lime-50']), 2))
"
```

- [ ] **Step 5: Format and commit**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
/home/dan/miniforge3/envs/helao/bin/black \
  helao/ui/shared/palette.py helao/core/tests/test_palette.py
git status --short --branch
git add helao/ui/shared/palette.py helao/core/tests/test_palette.py
git commit -m "feat(ui): a page tint for the composition route

lime-50, chosen by measurement. Of the four unused 50-level candidates it is
the only one that is both further from its nearest existing tint (dE 5.30 to
amber-50) than the existing tints are from each other (minimum pairwise 3.21)
and leaves every table border's weakest surface unchanged. indigo-50 fails both
counts and would add a fourth tint on which slate-500 is under the body floor.

slate-500 on lime-50 measures 4.60 and so does not join the failing set, which
is the other half of that test's point: which surfaces fail is measured, not
predicted from shade names.

test_reflex_page_tints_cover_the_shell_routes fails until the route lands. The
tint and the route are separately reviewable and the failing assertion is what
says the pair is incomplete.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: `CompositionState` — data loading and selection

**Files:**
- Create: `helao/ui/reflex/composition.py`
- Test: `helao/core/tests/test_reflex_composition.py`

**Interfaces:**
- Consumes: Tasks 1–6 (`shared.platemap`, `shared.composition.{model,api,grouping,ternary,interp}`) and Task 7 (`plots.ternary`).
- Produces:
  - `configure(world_cfg: dict, server_key: str) -> None`
  - `CompositionState` with vars `plate_id`, `run_use_choice`, `sequence_choice`,
    `transition_choice`, `unit_choice`, `vertex_a`, `vertex_b`, `vertex_c`,
    `interpolate`, `status`, `error`, `platemap_note`, `progress`,
    `selected_label`, `detail_rows: list[list[str]]`, `transition_options: list[str]`,
    `unit_options: list[str]`, `run_use_options: list[str]`, `sequence_options: list[str]`,
    and three chart triples `map_spec`/`map_url`/`map_layout`,
    `tern_spec`/`tern_url`/`tern_layout`, `spec_spec`/`spec_url`/`spec_layout`
  - `build_page()` — added in Task 10

- [ ] **Step 1: Write the failing test**

Create `helao/core/tests/test_reflex_composition.py`:

```python
# helao/core/tests/test_reflex_composition.py
"""CompositionState: loading, grouping, plotting and selection.

Every test here stubs the API layer. Nothing performs a request, and nothing
needs a platemap.
"""

import asyncio

import pytest

from helao.ui.reflex import composition
from helao.ui.shared.composition import grouping
from helao.ui.shared.composition.model import CompositionRecord


def record(**kwargs) -> CompositionRecord:
    base = dict(
        plate_id=10244,
        sample_no=1,
        global_label="legacy__solid__10244_1",
        run_use="post_anneal",
        sequence_uuid="06a7e382-a773-731d-8000-d7e3e21eacec",
        sequence_timestamp="2026-08-13T11:54:21.000000",
        process_uuid="p1",
        process_timestamp="2026-08-13T11:57:41.000000",
        quant_action_uuid="a1",
        quant_file_name="q.json",
        spectrum_action_uuid="a1",
        spectrum_file_name="s.json",
        values={
            "Co.K": {"net_counts": 271.2, "atomic_fraction": 0.167},
            "Y.K": {"net_counts": 792.1, "atomic_fraction": 0.814},
            "Pt.L": {"net_counts": 44.7, "atomic_fraction": 0.019},
        },
    )
    base.update(kwargs)
    return CompositionRecord(**base)


RECORDS = [record(), record(sample_no=2, run_use="pre_anneal", process_uuid="p2")]

PM_ROWS = [
    {"sample_no": 1, "x": 0.0, "y": 0.0, "entry": {}},
    {"sample_no": 2, "x": 1.0, "y": 0.0, "entry": {}},
    {"sample_no": 3, "x": 0.0, "y": 1.0, "entry": {}},
    {"sample_no": 4, "x": 1.0, "y": 1.0, "entry": {}},
    {"sample_no": 5, "x": 0.5, "y": 0.5, "entry": {}},
]


def test_plate_id_must_be_an_integer() -> None:
    assert composition.parse_plate_id("10244") == 10244
    assert composition.parse_plate_id(" 10244 ") == 10244
    assert composition.parse_plate_id("plate ten") is None
    assert composition.parse_plate_id("") is None


def test_series_for_returns_one_value_per_record_with_none_for_missing() -> None:
    """A record missing the selected transition keeps its slot: the value array
    and the position array are indexed together downstream."""
    values = composition.series_for(RECORDS, "Co.K", "net_counts")
    assert values == [271.2, 271.2]
    missing = composition.series_for(RECORDS, "Fe.K", "net_counts")
    assert missing == [None, None]


def test_map_arrays_join_on_the_platemap_sample_no() -> None:
    xs, ys, values, kept = composition.map_arrays(
        RECORDS, PM_ROWS, "Co.K", "net_counts"
    )
    assert xs == [0.0, 1.0]
    assert ys == [0.0, 0.0]
    assert values == [271.2, 271.2]
    assert [r.sample_no for r in kept] == [1, 2]


def test_map_arrays_drops_a_record_with_no_platemap_row() -> None:
    xs, _, _, kept = composition.map_arrays(
        [record(sample_no=9999)], PM_ROWS, "Co.K", "net_counts"
    )
    assert xs == []
    assert kept == []


def test_map_arrays_drops_a_record_whose_value_is_none() -> None:
    """None is an uncalibrated transition, not zero. Plotting it as 0.0 would
    read as a measurement."""
    blank = record(sample_no=2, values={"Co.K": {"net_counts": None}})
    xs, _, values, kept = composition.map_arrays(
        [blank], PM_ROWS, "Co.K", "net_counts"
    )
    assert xs == []
    assert values == []
    assert kept == []


def test_detail_rows_lists_every_transition_and_unit() -> None:
    rows = composition.detail_rows(record())
    assert rows[0] == ["transition", "atomic_fraction", "net_counts"]
    assert ["Co.K", "0.167", "271.2"] in rows


def test_detail_rows_shows_a_missing_value_as_a_dash() -> None:
    rows = composition.detail_rows(record(values={"Y.L": {"atomic_fraction": None}}))
    assert ["Y.L", "-"] in rows


def test_nearest_record_picks_by_distance_in_the_plotted_plane() -> None:
    xs = [0.0, 1.0]
    ys = [0.0, 0.0]
    assert composition.nearest_record(RECORDS, xs, ys, 0.9, 0.05) is RECORDS[1]


def test_nearest_record_on_an_empty_plot_returns_none() -> None:
    assert composition.nearest_record([], [], [], 0.0, 0.0) is None


def test_load_populates_records_and_options(monkeypatch) -> None:
    """The whole retrieve path, with the API layer stubbed."""

    async def fake_search(client, plate_id, size=500):
        return [{"process_uuid": "p1"}]

    async def fake_sequences(client, uuids):
        return {}

    async def fake_quant(client, action_uuid, file_name):
        return {
            "transition": ["Co.K", "Y.K", "Pt.L"],
            "net_counts": [271.2, 792.1, 44.7],
        }

    monkeypatch.setattr(composition.api, "search_processes", fake_search)
    monkeypatch.setattr(composition.api, "fetch_sequences", fake_sequences)
    monkeypatch.setattr(composition.api, "fetch_quant", fake_quant)
    monkeypatch.setattr(composition.api, "get_client", lambda: object())
    monkeypatch.setattr(
        composition.model,
        "record_from_process",
        lambda item, seqs: record(),
    )

    loaded = asyncio.run(composition.load_records(10244))
    assert len(loaded.records) == 1
    assert loaded.failures == 0
    assert grouping.ALL in grouping.run_use_options(loaded.records)


def test_load_counts_a_failed_quant_fetch_rather_than_raising(monkeypatch) -> None:
    """One unreadable HLO out of 497 must not cost the other 496."""

    async def fake_search(client, plate_id, size=500):
        return [{"process_uuid": "p1"}, {"process_uuid": "p2"}]

    async def fake_sequences(client, uuids):
        return {}

    calls = {"n": 0}

    async def fake_quant(client, action_uuid, file_name):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("500 from S3")
        return {"transition": ["Co.K"], "net_counts": [1.0]}

    monkeypatch.setattr(composition.api, "search_processes", fake_search)
    monkeypatch.setattr(composition.api, "fetch_sequences", fake_sequences)
    monkeypatch.setattr(composition.api, "fetch_quant", fake_quant)
    monkeypatch.setattr(composition.api, "get_client", lambda: object())
    monkeypatch.setattr(
        composition.model, "record_from_process", lambda item, seqs: record()
    )

    loaded = asyncio.run(composition.load_records(10244))
    assert loaded.failures == 1
    assert len(loaded.records) == 1


def test_configure_records_the_world_config() -> None:
    composition.configure({"servers": {}}, "UI")
    assert composition.world_config() == {"servers": {}}


def test_platemap_note_names_the_missing_piece(monkeypatch) -> None:
    """Three different causes, three different notes: the operator's next move
    differs in each."""
    monkeypatch.setattr(composition.platemap, "plate_api_for_config", lambda cfg: None)
    composition.configure({"servers": {}}, "UI")
    rows, note = composition.platemap_for(10244)
    assert rows == []
    assert "no plate API" in note


def test_platemap_note_when_access_is_unavailable(monkeypatch) -> None:
    class NoAccess:
        has_access = False

    monkeypatch.setattr(
        composition.platemap, "plate_api_for_config", lambda cfg: NoAccess()
    )
    composition.configure({"servers": {}}, "UI")
    rows, note = composition.platemap_for(10244)
    assert rows == []
    assert "HELAO_CREDENTIALS" in note


def test_platemap_note_when_the_plate_will_not_load(monkeypatch) -> None:
    class Raises:
        has_access = True

        def get_platemap_plateid(self, plate_id):
            raise RuntimeError("no such plate")

    monkeypatch.setattr(
        composition.platemap, "plate_api_for_config", lambda cfg: Raises()
    )
    composition.configure({"servers": {}}, "UI")
    rows, note = composition.platemap_for(10244)
    assert rows == []
    assert "10244" in note
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async timeout 600 \
  /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_reflex_composition.py -v
```

Expected: `ImportError: cannot import name 'composition'`.

- [ ] **Step 3: Write the module's logic half**

Create `helao/ui/reflex/composition.py` with everything except `build_page`
(Task 10 adds that):

```python
# helao/ui/reflex/composition.py
"""The `/composition` page: XRF analyses across one plate.

An operator enters a plate id; the page loads every XRF process the metadata
API has for that plate, groups them by ``run_use`` and by sequence, and plots a
chosen transition and unit as a platemap scatter and a ternary diagram.
Clicking a point shows that sample's full analysis output and its spectrum.

Three rules this stack has already paid for, restated because each fails at a
different moment:

* ``plots.chart`` is bound **once**, in :func:`build_page`. The facade functions
  are called from event handlers and their payloads assigned into state. A
  facade call in the body paints once and never updates.
* There is **no polling loop**. ``on_unmount`` does not fire on tab close, so a
  server-side ``while True`` outlives the browser. This page has no cadence:
  every render follows a button press or a click.
* Every ``rx.foreach`` var carries an element annotation. A bare ``list`` fails
  the *frontend build* with ``ForeachVarError``, not at import.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Optional

import reflex as rx

from helao.helpers import helao_logging as logging
from helao.ui.reflex import plots
from helao.ui.shared import platemap
from helao.ui.shared.composition import api, grouping, interp, model, ternary

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Concurrent quantification fetches. Matches the bound the existing XRFS
#: lookups use against this API.
MAX_CONCURRENT_FETCHES = 30

#: How a missing value reads in the details table.
MISSING = "-"

_SETTINGS: dict = {}
_SETTINGS_LOCK = threading.Lock()


def configure(world_cfg: dict, server_key: str) -> None:
    """Record the config this page resolves its plate API from.

    Called from ``build_app``, as ``configure_operator`` and
    ``configure_control`` already are.
    """
    with _SETTINGS_LOCK:
        _SETTINGS.update({"world_cfg": world_cfg or {}, "server_key": server_key})


def world_config() -> dict:
    """The config recorded by :func:`configure`."""
    with _SETTINGS_LOCK:
        return _SETTINGS.get("world_cfg") or {}


def parse_plate_id(raw: str) -> Optional[int]:
    """The entered plate id, or ``None`` when it is not one."""
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Loaded:
    """What one Retrieve produced."""

    records: list
    failures: int


async def load_records(plate_id: int) -> Loaded:
    """Every XRF record for *plate_id*, with its analysis values folded in.

    The quantification fetches fan out under a semaphore and collect
    exceptions: one unreadable HLO out of several hundred must be counted and
    reported, not allowed to abort the load.
    """
    client = api.get_client()
    items = await api.search_processes(client, plate_id)
    uuids = sorted({str(item.get("sequence_uuid") or "") for item in items})
    sequences = await api.fetch_sequences(client, uuids)
    records = [
        record
        for record in (model.record_from_process(item, sequences) for item in items)
        if record is not None
    ]
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

    async def _one(record):
        async with semaphore:
            return await api.fetch_quant(
                client, record.quant_action_uuid, record.quant_file_name
            )

    payloads = await asyncio.gather(
        *(_one(record) for record in records), return_exceptions=True
    )
    loaded = []
    failures = 0
    for record, payload in zip(records, payloads):
        if isinstance(payload, Exception):
            failures += 1
            LOGGER.warning(
                f"composition could not read {record.quant_file_name} "
                f"for action {record.quant_action_uuid}: {payload}"
            )
            continue
        loaded.append(model.with_values(record, payload))
    return Loaded(records=loaded, failures=failures)


def platemap_for(plate_id: int) -> tuple:
    """``(rows, note)`` for *plate_id*, from the configured plate API.

    The note distinguishes three causes, because the operator's next move
    differs in each: no plate API is declared in this config, credentials are
    unavailable, or this particular plate would not load.
    """
    plate_api = platemap.plate_api_for_config(world_config())
    if plate_api is None:
        return [], "no plate API is configured, so there is no platemap to plot against"
    if not plate_api.has_access:
        return (
            [],
            "the platemap needs credentials; set HELAO_CREDENTIALS to a readable "
            "environment file",
        )
    try:
        pmdata = plate_api.get_platemap_plateid(plate_id)
    except Exception as exc:
        LOGGER.warning(f"composition could not load plate {plate_id}: {exc}")
        return [], f"plate {plate_id}'s platemap could not be read: {exc}"
    rows = platemap.platemap_rows(pmdata)
    if not rows:
        return [], f"plate {plate_id} has no platemap rows with usable coordinates"
    return rows, ""


def series_for(records, transition: str, unit: str) -> list:
    """One value per record, ``None`` where the record has no such measurement.

    The slot is kept rather than dropped because the caller indexes this
    against a parallel array of records.
    """
    out = []
    for record in records or []:
        out.append((record.values.get(transition) or {}).get(unit))
    return out


def map_arrays(records, pm_rows, transition: str, unit: str) -> tuple:
    """``(xs, ys, values, kept_records)`` for the plate-map scatter.

    Joined on the platemap's own ``sample_no``. A record with no platemap row,
    or whose selected value is ``None``, is dropped from all four outputs
    together -- ``None`` is an uncalibrated transition, and plotting it as
    ``0.0`` would read as a measurement.
    """
    by_sample = {row["sample_no"]: row for row in pm_rows or []}
    xs, ys, values, kept = [], [], [], []
    for record in records or []:
        row = by_sample.get(record.sample_no)
        if row is None:
            continue
        value = (record.values.get(transition) or {}).get(unit)
        if value is None:
            continue
        xs.append(row["x"])
        ys.append(row["y"])
        values.append(value)
        kept.append(record)
    return xs, ys, values, kept


def detail_rows(record) -> list:
    """The selected sample's whole analysis output, as table rows.

    First row is the header. Every transition is listed against every unit any
    transition carries, so a missing measurement shows as a gap rather than
    shifting the columns.
    """
    if record is None:
        return []
    units = sorted({unit for per_unit in record.values.values() for unit in per_unit})
    rows = [["transition"] + units]
    for transition in sorted(record.values):
        per_unit = record.values[transition]
        cells = []
        for unit in units:
            value = per_unit.get(unit)
            cells.append(MISSING if value is None else f"{value:g}")
        rows.append([transition] + cells)
    return rows


def nearest_record(records, xs, ys, x: float, y: float):
    """The record nearest ``(x, y)`` in the plotted plane, or ``None``.

    The chart reports a **coordinate**, never a row id: ``xy_component`` wires
    only ``on_select``, whose payload carries ``x`` and ``y``. Matching happens
    in the plane the click is in, which on the ternary diagram is the
    transformed plane -- searching the barycentric triples would find a
    different point wherever the triangle is anisotropic on screen.
    """
    if not records or not xs:
        return None
    index = min(
        range(len(xs)), key=lambda i: (xs[i] - x) ** 2 + (ys[i] - y) ** 2
    )
    return records[index] if index < len(records) else None


class CompositionState(rx.State):
    """Everything the composition page holds."""

    plate_id: str = ""
    status: str = ""
    error: str = ""
    platemap_note: str = ""
    progress: str = ""

    run_use_choice: str = grouping.ALL
    sequence_choice: str = grouping.ALL
    transition_choice: str = ""
    unit_choice: str = ""
    vertex_a: str = ""
    vertex_b: str = ""
    vertex_c: str = ""
    interpolate: bool = False

    run_use_options: list[str] = []
    sequence_options: list[str] = []
    transition_options: list[str] = []
    unit_options: list[str] = []

    selected_label: str = ""
    detail_rows: list[list[str]] = []

    map_spec: dict = {}
    map_url: str = ""
    map_layout: str = ""
    tern_spec: dict = {}
    tern_url: str = ""
    tern_layout: str = ""
    spec_spec: dict = {}
    spec_url: str = ""
    spec_layout: str = ""

    version: int = 0

    #: Backend vars: the browser needs the rendered points, not the records.
    _records: list = []
    _pm_rows: list = []
    _plotted: list = []
    _plotted_xs: list = []
    _plotted_ys: list = []

    def panel_key(self) -> str:
        """Session-scoped buffer-store key.

        The store holds one frame per key while ``version`` is per-session
        state, so a shared key would 404 two tabs into frozen charts.
        """
        return f"composition-{self.router.session.client_token}"

    @rx.event
    def set_plate_id(self, value: str):
        self.plate_id = value

    @rx.event
    def set_run_use(self, value: str):
        self.run_use_choice = value

    @rx.event
    def set_sequence(self, value: str):
        self.sequence_choice = value

    @rx.event
    def set_transition(self, value: str):
        self.transition_choice = value

    @rx.event
    def set_unit(self, value: str):
        self.unit_choice = value

    @rx.event
    def set_vertex_a(self, value: str):
        self.vertex_a = value

    @rx.event
    def set_vertex_b(self, value: str):
        self.vertex_b = value

    @rx.event
    def set_vertex_c(self, value: str):
        self.vertex_c = value

    @rx.event
    def set_interpolate(self, value: bool):
        """A checkbox value is a bool, never a string.

        ``bool("False")`` is ``True``, so routing this through the text
        coercion would invert every unchecked box.
        """
        self.interpolate = bool(value)

    @rx.event(background=True)
    async def retrieve(self, _tick: str = ""):
        """Load every XRF record for the entered plate id.

        The default argument is not decoration: a handler bound to a button
        receives a ``PointerEventInfo``, and one bound to anything that supplies
        a value receives that value. Binding a no-argument handler to a button
        raises ``EventHandlerArgTypeMismatchError`` **at render**.
        """
        async with self:
            plate_id = parse_plate_id(self.plate_id)
            self.error = ""
            self.status = ""
            self.progress = ""
        if plate_id is None:
            async with self:
                self.error = f"'{self.plate_id}' is not a plate id"
            return
        async with self:
            self.status = f"loading plate {plate_id}..."
        try:
            loaded = await load_records(plate_id)
        except Exception as exc:
            LOGGER.warning(f"composition could not load plate {plate_id}: {exc}")
            async with self:
                self.error = f"plate {plate_id} could not be loaded: {exc}"
                self.status = ""
            return
        rows, note = platemap_for(plate_id)
        async with self:
            self._records = loaded.records
            self._pm_rows = rows
            self.platemap_note = note
            self.run_use_options = grouping.run_use_options(loaded.records)
            self.sequence_options = grouping.sequence_options(loaded.records)
            self.transition_options = model.transition_names(loaded.records)
            self.unit_options = model.unit_names(loaded.records)
            self.run_use_choice = grouping.ALL
            self.sequence_choice = grouping.ALL
            self.transition_choice = (
                self.transition_options[0] if self.transition_options else ""
            )
            self.unit_choice = self.unit_options[0] if self.unit_options else ""
            vertices = self.transition_options[:3]
            self.vertex_a = vertices[0] if len(vertices) > 0 else ""
            self.vertex_b = vertices[1] if len(vertices) > 1 else ""
            self.vertex_c = vertices[2] if len(vertices) > 2 else ""
            failed = f", {loaded.failures} unreadable" if loaded.failures else ""
            self.status = (
                f"plate {plate_id}: {len(loaded.records)} XRF processes{failed}"
            )

    @rx.event
    def plot(self, _tick: str = ""):
        """Render the plate map and the ternary diagram from the selections."""
        self.error = ""
        records = grouping.filter_records(
            self._records,
            run_use=self.run_use_choice,
            sequence=self.sequence_choice,
        )
        if not records:
            self.status = "nothing matches this grouping"
            return
        self.version += 1
        self._draw_map(records)
        self._draw_ternary(records)

    def _draw_map(self, records) -> None:
        """The plate-map scatter, measured or interpolated."""
        if not self._pm_rows:
            return
        xs, ys, values, kept = map_arrays(
            records, self._pm_rows, self.transition_choice, self.unit_choice
        )
        self._plotted = kept
        self._plotted_xs = list(xs)
        self._plotted_ys = list(ys)
        plot_xs, plot_ys, plot_values = xs, ys, values
        if self.interpolate:
            target_xs = [row["x"] for row in self._pm_rows]
            target_ys = [row["y"] for row in self._pm_rows]
            surface = interp.rbf_surface(xs, ys, values, target_xs, target_ys)
            if surface.size == 0:
                self.status = (
                    f"fewer than {interp.MIN_POINTS} measured points; "
                    f"showing the measured samples instead"
                )
            else:
                plot_xs, plot_ys, plot_values = target_xs, target_ys, surface.tolist()
        payload = plots.scatter_map(
            plot_xs,
            plot_ys,
            values=plot_values or None,
            x_label="x (mm)",
            y_label="y (mm)",
            panel_id=f"{self.panel_key()}-map",
            version=self.version,
        )
        self.map_spec = payload.spec
        self.map_url = payload.buffer_url
        self.map_layout = payload.layout

    def _draw_ternary(self, records) -> None:
        """The ternary diagram over the three chosen vertices."""
        vertices = (self.vertex_a, self.vertex_b, self.vertex_c)
        if not all(vertices):
            self.error = "pick three transitions for the ternary vertices"
            return
        unit = self.unit_choice
        components = [
            [
                value if value is not None else float("nan")
                for value in series_for(records, vertex, unit)
            ]
            for vertex in vertices
        ]
        payload = plots.ternary(
            components[0],
            components[1],
            components[2],
            labels=vertices,
            panel_id=f"{self.panel_key()}-tern",
            version=self.version,
        )
        self.tern_spec = payload.spec
        self.tern_url = payload.buffer_url
        self.tern_layout = payload.layout

    @rx.event(background=True)
    async def on_map_select(self, payload: dict):
        """Snap to the measured sample nearest a click on the plate map.

        On the interpolated surface a click may land where nothing was
        measured; it resolves to the nearest measured sample and the details
        panel names which, so an interpolated value is never shown as a
        measurement.
        """
        x = _coord(payload, "x")
        y = _coord(payload, "y")
        if x is None or y is None:
            return
        async with self:
            record = nearest_record(
                self._plotted, self._plotted_xs, self._plotted_ys, x, y
            )
        await self._select(record)

    async def _select(self, record) -> None:
        """Fill the details panel and load the spectrum for *record*."""
        if record is None:
            return
        async with self:
            self.selected_label = (
                f"{record.global_label}   sample {record.sample_no}   "
                f"{record.run_use or '(no run_use)'}"
            )
            self.detail_rows = detail_rows(record)
        if not record.spectrum_action_uuid or not record.spectrum_file_name:
            async with self:
                self.error = "this process recorded no spectrum file"
            return
        try:
            series = await api.fetch_spectrum(
                api.get_client(),
                record.spectrum_action_uuid,
                record.spectrum_file_name,
            )
        except Exception as exc:
            LOGGER.warning(
                f"composition could not read the spectrum for "
                f"{record.process_uuid}: {exc}"
            )
            async with self:
                self.error = f"the spectrum could not be read: {exc}"
            return
        ev = series.get("ev") or []
        intensity = series.get("intensity") or []
        if not ev or not intensity:
            async with self:
                self.error = "the spectrum file carried no ev/intensity series"
            return
        async with self:
            self.version += 1
            payload = plots.spectra(
                ev,
                {record.global_label: intensity},
                x_label="ev",
                y_label="intensity",
                panel_id=f"{self.panel_key()}-spec",
                version=self.version,
            )
            self.spec_spec = payload.spec
            self.spec_url = payload.buffer_url
            self.spec_layout = payload.layout


def _coord(payload: Optional[dict], key: str) -> Optional[float]:
    """One coordinate out of an ``on_select`` payload."""
    try:
        return float((payload or {}).get(key))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async timeout 600 \
  /home/dan/miniforge3/envs/helao/bin/python -m pytest \
  helao/core/tests/test_reflex_composition.py -v
```

Expected: PASS, 15 tests.

- [ ] **Step 5: Format and commit**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
/home/dan/miniforge3/envs/helao/bin/black \
  helao/ui/reflex/composition.py helao/core/tests/test_reflex_composition.py
git status --short --branch
git add helao/ui/reflex/composition.py helao/core/tests/test_reflex_composition.py
git commit -m "feat(ui): CompositionState, the composition page's logic half

The plate-map join is on the platemap's own sample_no, never on a row index:
records carry a sample number parsed from their global label, and positional
numbering would pair the right value with the wrong position. A None value is
dropped rather than plotted as 0.0 -- an uncalibrated transition has no
measurement, and a zero reads as one.

Selection resolves a coordinate, not an index: xy_component wires only
on_select, whose payload carries x and y. On the interpolated surface a click
can land where nothing was measured, so it snaps to the nearest measured sample
and the details panel names which.

The quant fan-out is bounded at 30 and collects exceptions, so one unreadable
HLO out of several hundred is counted and reported rather than aborting the
load.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: The page body and the `/composition` route

**Files:**
- Modify: `helao/ui/reflex/composition.py` (append `build_page`)
- Modify: `helao/ui/reflex/app.py` (`SHELL_ROUTES` line 75; `_nav()` line 282; imports near line 47; `build_app` near lines 451 and 522)
- Test: `helao/core/tests/test_reflex_routes_e2e.py`, `helao/core/tests/test_reflex_composition.py`

**Interfaces:**
- Consumes: `CompositionState` and the module functions from Task 9; `plots.chart`; `palette.reflex_page_class` via `app._page`.
- Produces: `composition.build_page()`, `SHELL_ROUTES` containing `/composition`.

- [ ] **Step 1: Write the failing tests**

Append to `helao/core/tests/test_reflex_composition.py`:

```python
def test_build_page_renders() -> None:
    """Rendered, not merely imported. A handler bound to both a button and
    something that supplies a value raises at render, not at import, so an
    import-only test cannot see it."""
    assert composition.build_page() is not None


def test_every_foreach_var_carries_an_element_annotation() -> None:
    """A bare `list` fails the frontend build with ForeachVarError, which
    surfaces only at `reflex export`."""
    hints = composition.CompositionState.__annotations__
    assert hints["detail_rows"] == list[list[str]]
    for name in (
        "run_use_options",
        "sequence_options",
        "transition_options",
        "unit_options",
    ):
        assert hints[name] == list[str], name
```

Append to `helao/core/tests/test_reflex_routes_e2e.py`:

```python
def test_composition_route_is_the_real_page_not_a_stub(reflex_cfg):
    """A passing route test that renders a stub is worse than no test."""
    from helao.ui.reflex import composition as app_reflex

    from helao.ui.reflex.app import build_app

    build_app(reflex_cfg, "UI")
    assert app_reflex.CompositionState.__name__ == "CompositionState"
    assert callable(app_reflex.build_page)


def test_composition_state_handlers_are_registered_without_compiling_pages(reflex_cfg):
    """The same freeze the panels hit: a state class first touched inside
    `add_page`'s lazy callable never exists in a `--backend-only` process, so
    the browser calls handlers the backend has never heard of."""
    from helao.ui.reflex import composition as app_reflex

    from helao.ui.reflex.app import build_app

    build_app(reflex_cfg, "UI")
    handlers = app_reflex.CompositionState.event_handlers
    for name in ("retrieve", "plot", "on_map_select", "set_plate_id"):
        assert name in handlers, f"{name} not registered; have {sorted(handlers)}"


def test_composition_page_is_configured_at_build(reflex_cfg):
    from helao.ui.reflex import composition as app_reflex

    from helao.ui.reflex.app import build_app

    build_app(reflex_cfg, "UI")
    assert app_reflex.world_config().get("servers")
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
export PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async
P=/home/dan/miniforge3/envs/helao/bin/python
timeout 600 $P -m pytest helao/core/tests/test_reflex_composition.py -v
timeout 900 $P -m pytest helao/core/tests/test_reflex_routes_e2e.py -v
```

Expected: `AttributeError: module ... has no attribute 'build_page'`, and the
routes test failing on the missing `/composition` route.

- [ ] **Step 3: Write `build_page`**

Append to `helao/ui/reflex/composition.py`:

```python
def _controls():
    """The plate-id field, the four dropdowns and the two buttons."""
    return rx.vstack(
        rx.hstack(
            rx.input(
                placeholder="plate id",
                value=CompositionState.plate_id,
                on_change=CompositionState.set_plate_id,
                width="10em",
            ),
            rx.button("Retrieve", on_click=CompositionState.retrieve("")),
            rx.text(CompositionState.status, size="1"),
            spacing="3",
            align="center",
        ),
        rx.hstack(
            rx.text("run_use", size="1", class_name=reflex_muted_text_class()),
            rx.select(
                CompositionState.run_use_options,
                value=CompositionState.run_use_choice,
                on_change=CompositionState.set_run_use,
                width="12em",
            ),
            rx.text("sequence", size="1", class_name=reflex_muted_text_class()),
            rx.select(
                CompositionState.sequence_options,
                value=CompositionState.sequence_choice,
                on_change=CompositionState.set_sequence,
                width="24em",
            ),
            spacing="3",
            align="center",
        ),
        rx.hstack(
            rx.text("transition", size="1", class_name=reflex_muted_text_class()),
            rx.select(
                CompositionState.transition_options,
                value=CompositionState.transition_choice,
                on_change=CompositionState.set_transition,
                width="10em",
            ),
            rx.text("unit", size="1", class_name=reflex_muted_text_class()),
            rx.select(
                CompositionState.unit_options,
                value=CompositionState.unit_choice,
                on_change=CompositionState.set_unit,
                width="14em",
            ),
            rx.button("Plot", on_click=CompositionState.plot("")),
            spacing="3",
            align="center",
        ),
        width="100%",
        spacing="2",
    )


def _map_panel():
    """The plate map, or the note saying why there is none."""
    return rx.vstack(
        rx.hstack(
            rx.checkbox(
                "RBF interpolate",
                checked=CompositionState.interpolate,
                on_change=CompositionState.set_interpolate,
            ),
            spacing="3",
            align="center",
        ),
        rx.cond(
            CompositionState.platemap_note != "",
            rx.text(
                CompositionState.platemap_note,
                size="1",
                class_name=reflex_muted_text_class(),
            ),
            plots.chart(
                CompositionState.map_spec,
                CompositionState.map_url,
                CompositionState.map_layout,
                height=420,
                on_select=CompositionState.on_map_select,
            ),
        ),
        width="100%",
        spacing="2",
    )


def _ternary_panel():
    """The ternary diagram and its three vertex selectors."""
    return rx.vstack(
        rx.hstack(
            rx.select(
                CompositionState.transition_options,
                value=CompositionState.vertex_a,
                on_change=CompositionState.set_vertex_a,
                width="9em",
            ),
            rx.select(
                CompositionState.transition_options,
                value=CompositionState.vertex_b,
                on_change=CompositionState.set_vertex_b,
                width="9em",
            ),
            rx.select(
                CompositionState.transition_options,
                value=CompositionState.vertex_c,
                on_change=CompositionState.set_vertex_c,
                width="9em",
            ),
            spacing="3",
            align="center",
        ),
        plots.chart(
            CompositionState.tern_spec,
            CompositionState.tern_url,
            CompositionState.tern_layout,
            height=420,
        ),
        width="100%",
        spacing="2",
    )


def _details_panel():
    """The selected sample's analysis output, and its spectrum."""
    return rx.vstack(
        rx.text(CompositionState.selected_label, size="2"),
        rx.table.root(
            rx.table.body(
                rx.foreach(
                    CompositionState.detail_rows,
                    lambda row: rx.table.row(
                        rx.foreach(row, lambda cell: rx.table.cell(cell))
                    ),
                )
            ),
            class_name=reflex_table_class("action"),
            width="100%",
        ),
        plots.chart(
            CompositionState.spec_spec,
            CompositionState.spec_url,
            CompositionState.spec_layout,
            height=300,
        ),
        width="100%",
        spacing="2",
    )


def build_page():
    """Render the composition page.

    Returns:
        rx.Component: The page body.
    """
    return rx.vstack(
        _controls(),
        rx.cond(
            CompositionState.error != "",
            rx.text(CompositionState.error, class_name="text-red-600", size="1"),
        ),
        rx.hstack(
            _map_panel(),
            _ternary_panel(),
            width="100%",
            spacing="4",
            align="start",
        ),
        _details_panel(),
        width="100%",
        spacing="4",
        padding_x="1em",
    )
```

Add to the module's imports:

```python
from helao.ui.shared.palette import reflex_muted_text_class, reflex_table_class
```

- [ ] **Step 4: Wire the route into `app.py`**

Four edits in `helao/ui/reflex/app.py`:

1. `SHELL_ROUTES` (line 75) becomes:

```python
SHELL_ROUTES = (
    "/",
    "/live",
    "/action",
    "/operator",
    "/browser",
    "/control",
    "/composition",
)
```

2. Add the imports beside the existing operator/browser ones:

```python
from helao.ui.reflex.composition import build_page as composition_page
from helao.ui.reflex.composition import configure as configure_composition
```

3. In `_nav()`, after the Control link:

```python
        rx.link("Composition", href="/composition"),
```

4. In `build_app`, beside `configure_control(world_cfg, server_key)`:

```python
    configure_composition(world_cfg, server_key)
```

and after the `/control` `add_page`:

```python
    application.add_page(
        lambda: _page("Composition", composition_page(), "/composition"),
        route="/composition",
        title="HELAO composition",
    )
```

- [ ] **Step 5: Run the full affected suite**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
export PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async
P=/home/dan/miniforge3/envs/helao/bin/python
timeout 600 $P -m pytest helao/core/tests/test_reflex_composition.py -v
timeout 900 $P -m pytest helao/core/tests/test_reflex_routes_e2e.py -v
timeout 600 $P -m pytest helao/core/tests/test_palette.py -q
timeout 600 $P -m pytest helao/core/tests/test_reflex_plots.py -q
timeout 900 $P -m pytest helao/core/tests/test_reflex_operator.py -q
timeout 900 $P -m pytest helao/core/tests/test_standalone_operator.py -q
timeout 600 $P -m pytest helao/core/tests/test_reflex_config.py -q
timeout 600 $P -m pytest helao/core/tests/test_shared_platemap.py -q
```

Expected: all PASS, including
`test_reflex_page_tints_cover_the_shell_routes`, which failed at the end of
Task 8 and is now satisfied by the route.

- [ ] **Step 6: Type check**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
/home/dan/miniforge3/envs/helao/bin/python -m pyright \
  helao/ui/reflex/composition.py helao/ui/shared/platemap.py \
  helao/ui/shared/composition/
```

Expected: no new errors. pyright is the authoritative checker here (basic mode,
`pyrightconfig.json`); do not remove existing `# type: ignore` directives.
**Check the output says a non-zero number of files were analyzed** — a run that
analyzes 0 files is a vacuous pass, not a clean one.

- [ ] **Step 7: Format and commit**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
/home/dan/miniforge3/envs/helao/bin/black \
  helao/ui/reflex/composition.py helao/ui/reflex/app.py \
  helao/core/tests/test_reflex_composition.py \
  helao/core/tests/test_reflex_routes_e2e.py
git status --short --branch
git add helao/ui/reflex/composition.py helao/ui/reflex/app.py \
  helao/core/tests/test_reflex_composition.py \
  helao/core/tests/test_reflex_routes_e2e.py
git commit -m "feat(ui): serve the composition page at /composition

The route is registered unconditionally like every other shell route --
params.pages selects which panels mount on /live and /action, it does not
decide which pages exist. The state class is created at import, before
add_page, because anything built inside that lazy callable never exists in a
--backend-only process and the browser then calls handlers the backend has
never heard of.

Handlers bound to buttons take their tick argument explicitly: rx.moment hands
its value to every handler on on_change while a button supplies a
PointerEventInfo, and the mismatch raises at render rather than at import,
which is why the test renders build_page() instead of importing it.

This also satisfies the tint assertion Task 8 deliberately left failing.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: Browser verification

The suites above cannot see a chart that renders blank, a dropdown whose
options never populate, or a Radix select whose value silently does not change.
This task is the manual gate and produces no code.

**Files:**
- None. Findings go into a follow-up task if anything fails.

- [ ] **Step 1: Launch the development Reflex group**

```bash
cd /mnt/STORAGE/repos/helao/helao-async
/home/dan/miniforge3/envs/helao/bin/python launch.py goldenreflex
```

The bundle rebuilds itself: the stamp hashes every `helao/` module the app
imported, so the new page and the edited palette both invalidate it. With
`.web/node_modules` warm an export is about 4 seconds. If the launcher
**refuses** and prints a `build_reflex_bundle.py` command, `node_modules` is
cold — run that command, which fetches about 270 MB, or set
`REFLEX_ALLOW_LOCAL_BUILD=1` to proceed anyway.

- [ ] **Step 2: Check the seven routes render**

Open each of `/`, `/live`, `/action`, `/operator`, `/browser`, `/control`,
`/composition`. Confirm `/composition` carries a visibly different canvas tint
from its neighbours and that the nav link reaches it.

- [ ] **Step 3: Exercise the page against a real plate**

Enter `10244`, press Retrieve. Expected: the status line reports about 497 XRF
processes, the run_use dropdown offers `All`, `post_anneal`, `pre_anneal`, and
the sequence dropdown offers two entries whose timestamps are
`2026-08-13T11:54:21` and `2026-09-10T17:02:37`.

**`rx.select` is a Radix select, not a `<select>`.** In a Playwright check,
`locator("select").select_option` matches nothing and *silently* leaves the
value alone, after which whatever you were actually testing gets blamed. Click
the `combobox`, then the `option` by role.

- [ ] **Step 4: Plot, toggle and click**

Press Plot. Confirm the plate map and the ternary diagram both paint. Toggle
RBF interpolate and confirm the map gains points at positions no measurement
covered. Click a point: the details panel must fill with every transition
against every unit, and the spectrum chart must paint with `ev` on x.

**Every chart is a WebGL context and Chrome caps them at 16.** This page has
three. An evicted chart stops drawing permanently while every other signal
reads healthy — data arrives, the view is mounted, the append fires, and xy
returns at its `_glLost` guard before touching the GPU, with nothing logged
server-side. If a chart goes blank after navigating between pages several
times, check the console for `Too many active WebGL contexts`.

- [ ] **Step 5: Check the degraded paths**

On a host with no `HELAO_CREDENTIALS`, confirm the plate-map panel shows the
note naming the credentials and that the ternary diagram, the details panel and
the spectrum still work. Confirm the RBF checkbox does nothing harmful there.

- [ ] **Step 6: Record the result**

If everything passes, note it in the PR description. If anything fails, open a
follow-up task rather than patching under time pressure: a control UI that
renders wrong is worse than one that visibly does not come up.

---

## Self-Review

**Spec coverage.** §2.1 → Task 3 `search_processes`. §2.2 → Task 3
`fetch_sequences`. §2.3 → Task 3 `fetch_quant` and Task 2 `with_values`. §2.4 →
Task 3 `fetch_spectrum` and Task 9 `_select`. §2.5 → Task 1
`plate_api_for_config` and Task 9 `platemap_for`. §2.6 → Task 1. §2.7 → Task 3
`_lookup_key`. §3.0 → Task 1. §3.1 → Task 3. §3.2 → Task 2. §3.3 → Task 4. §3.4
→ Task 5. §3.5 → Task 6. §3.6 → Task 7. §3.7 → Tasks 9 and 10. §4 → Tasks 9 and
10. §5 → Task 9 `load_records`. §6 → Tasks 8 and 10. §7 → the test file in every
task, plus Task 11 for the browser half. §8 is the exclusion list and needs no
task.

**Known gap, deliberate.** The spec's §5 mentions a running `n / total`
progress count. Task 9 reports the count once, at the end, in `status`. A
per-completion counter needs a second state write inside the gather, which
would rebuild the page body on every one of several hundred completions — the
churn the sample tables already had to be fixed for. If the load reads as frozen
during browser verification (Task 11), add a coarse counter that writes every
25 completions rather than every one.

**Type consistency.** `CompositionRecord` field names are used identically in
Tasks 2, 4, 9 and their tests. `grouping.ALL` and `grouping.NO_RUN_USE` are
referenced by name, never re-spelled. `plots.ternary`'s `labels` is a 3-tuple in
Task 7's implementation, its test, and Task 9's `_draw_ternary`.
`interp.MIN_POINTS` is read in Task 9 rather than repeated as `4`.
`platemap_rows` returns dicts keyed `sample_no`/`x`/`y`/`entry` in Task 1, and
Task 9's `map_arrays` and `_draw_map` read exactly those keys.
