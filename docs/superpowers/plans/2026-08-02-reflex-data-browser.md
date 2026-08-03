# Reflex Data Browser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the existing data browser as a Reflex page on `/browser`, driven by the same `sources`/`state`/`readers` logic the Bokeh browser uses, with no change to that logic and no change to the Bokeh app.

**Architecture:** A new `helao/core/servers/data_browser/app_reflex.py` sits beside `app.py`. It holds one `rx.State` subclass and one `build_page()` function. The scanned index DataFrame stays in a process-side cache keyed by Reflex session token — never in a state var — and the chart goes through the existing `plots` facade, which gains one function for independently-x'd traces. `helao/core/servers/reflex/app.py` swaps its `/browser` stub for this page.

**Tech Stack:** Reflex 0.9.7, xy 0.0.5, pandas, pytest, Playwright (headless chromium, already installed in the `helao` conda env).

## Global Constraints

- **`readers.py`, `state.py`, `sources.py`, and `app.py` are not edited.** If the Reflex UI needs something they do not expose, add it to the shared layer so the Bokeh app keeps working — never fork the behaviour into `app_reflex.py`. A diff touching those four files is a failed task unless the task says otherwise.
- **Bulk data never enters a Reflex state var.** The index DataFrame and `SelectedDataset.data` are bulk. State carries only what the UI renders.
- **Buffer-store keys are session-scoped**, `f"browser-{self.router.session.client_token}"`. A shared key 404s two tabs into permanently frozen charts.
- **Blocking I/O runs in `@rx.event(background=True)`.** `sources.get_index` walks the run tree; `state.load_selected` opens files.
- **This page's state is a plain `rx.State` subclass, not a mixin.** Mixins exist for `make_panel_state`, which mints one class per action server. One page, one state class.
- Trace kinds are exactly `"line"` and `"scatter"`, matching the Bokeh original.
- Python is the `helao` conda env: `/home/dan/miniforge3/envs/helao/bin/python`. Never the OS python.
- Run `black` on changed files immediately before every `git add`.
- `pyright` (basic) is authoritative; do not remove existing `# type: ignore`.
- Run pytest one file per process. The tree hangs when collected as a single session.

## File Structure

| File | Responsibility |
|---|---|
| `helao/core/servers/reflex/plots.py` (modify) | Gains `traces()` — the only facade entry that does not assume a shared x. |
| `helao/core/servers/data_browser/app_reflex.py` (new) | The Reflex page: `IndexCache`, `BrowserState`, `build_page()`. |
| `helao/core/servers/reflex/app.py` (modify) | `/browser` route resolves to the real page instead of `_stub_page`. |
| `helao/core/tests/test_reflex_plots.py` (modify) | `traces()` coverage. |
| `helao/core/tests/test_reflex_data_browser.py` (new) | Page-state transitions against a temp run tree. |
| `helao/core/tests/test_reflex_routes_e2e.py` (modify) | `/browser` is no longer a stub. |

---

### Task 1: `plots.traces` — independently-x'd traces

**Files:**
- Modify: `helao/core/servers/reflex/plots.py`
- Test: `helao/core/tests/test_reflex_plots.py`

**Interfaces:**
- Consumes: `_as_float_array`, `_finite_pairs`, `_axes`, `_publish`, `PALETTE` (all existing, private to `plots.py`).
- Produces: `plots.traces(series, *, kind="line", x_label="", y_label="", panel_id="traces", version=0) -> ChartPayload`, where `series` is `list[dict]` with keys `label`, `x`, `y`. Task 3 calls this.

**Why this exists:** `time_series` and `spectra` both take one `x` shared by every series. Each selected dataset in the browser carries its own x column, so neither fits, and forcing a shared x would silently misalign traces.

- [ ] **Step 1: Write the failing tests**

Append to `helao/core/tests/test_reflex_plots.py`:

```python
def test_traces_accepts_a_different_x_per_trace():
    """The gap this fills: time_series and spectra share one x across every
    series, but each selected dataset carries its own x column."""
    out = plots.traces(
        [
            {"label": "a", "x": np.linspace(0.0, 1.0, 5), "y": np.zeros(5)},
            {"label": "b", "x": np.linspace(0.0, 9.0, 30), "y": np.ones(30)},
        ]
    )
    assert isinstance(out, plots.ChartPayload)
    assert len(out.spec["traces"]) == 2


def test_traces_labels_each_trace():
    out = plots.traces([{"label": "only", "x": np.arange(3.0), "y": np.arange(3.0)}])
    assert out.spec["traces"][0]["name"] == "only"


def test_traces_supports_scatter():
    out = plots.traces(
        [{"label": "a", "x": np.arange(3.0), "y": np.arange(3.0)}], kind="scatter"
    )
    assert out.spec["traces"][0]["kind"] == "scatter"


def test_traces_rejects_an_unknown_kind():
    with pytest.raises(ValueError, match="kind"):
        plots.traces(
            [{"label": "a", "x": np.arange(3.0), "y": np.arange(3.0)}], kind="bogus"
        )


def test_traces_rejects_mismatched_x_and_y():
    with pytest.raises(ValueError, match="length"):
        plots.traces([{"label": "a", "x": np.zeros(5), "y": np.zeros(4)}])


def test_traces_tolerates_no_series():
    assert plots.traces([]) is not None


def test_traces_skips_an_all_non_finite_trace_without_raising():
    out = plots.traces(
        [
            {"label": "bad", "x": np.arange(3.0), "y": np.full(3, np.nan)},
            {"label": "good", "x": np.arange(3.0), "y": np.arange(3.0)},
        ]
    )
    assert len(out.spec["traces"]) == 1


def test_traces_carries_an_append_token_like_every_other_facade_entry():
    """Without spec.append the chart paints one frame and freezes."""
    out = plots.traces(
        [{"label": "a", "x": np.arange(3.0), "y": np.arange(3.0)}], version=4
    )
    assert out.spec["append"]["seq"] == 4
```

- [ ] **Step 2: Run them and watch them fail**

Run: `/home/dan/miniforge3/envs/helao/bin/python -m pytest -q helao/core/tests/test_reflex_plots.py -k traces`
Expected: FAIL, `AttributeError: module ... has no attribute 'traces'`

- [ ] **Step 3: Implement `traces`**

In `helao/core/servers/reflex/plots.py`, add `"traces"` to `__all__` and add this after `time_series`:

```python
#: Mark builders the browser's trace-type control selects between. Matches the
#: Bokeh data browser exactly; xy also ships `step`, but adding it here would
#: make the port a feature change rather than a re-rendering.
TRACE_KINDS = {"line": "line", "scatter": "scatter"}


def traces(
    series,
    *,
    kind: str = "line",
    x_label: str = "",
    y_label: str = "",
    panel_id: str = "traces",
    version: int = 0,
):
    """Render traces that each carry their own x values.

    :func:`time_series` and :func:`spectra` both take a single ``x`` shared by
    every series. The data browser overlays datasets read from unrelated files,
    so each has its own x column and a shared axis would misalign them.

    Args:
        series: Sequence of ``{"label": str, "x": array, "y": array}``.
        kind: ``"line"`` or ``"scatter"``.
        x_label: X axis label.
        y_label: Y axis label.
        panel_id: Stable panel identity for the buffer route.
        version: Monotonic data version; the browser refetches when it changes.

    Returns:
        ChartPayload: Assign into the panel state vars bound by :func:`chart`.
        Traces with no finite points are skipped; an empty ``series`` yields a
        valid empty chart.

    Raises:
        ValueError: If ``kind`` is unknown, or a trace's x and y differ in
            length.
    """
    if kind not in TRACE_KINDS:
        raise ValueError(
            f"unknown trace kind {kind!r}; expected one of {sorted(TRACE_KINDS)}"
        )
    builder = getattr(xy, TRACE_KINDS[kind])
    marks = []
    for idx, item in enumerate(series):
        xs = _as_float_array(item["x"])
        ys = _as_float_array(item["y"])
        # Checked before the finite filter: a length mismatch is a caller bug,
        # and dropping to the shorter of the two would hide it behind a plot
        # that looks plausible.
        if xs.size != ys.size:
            raise ValueError(
                f"trace '{item['label']}' has x length {xs.size} "
                f"and y length {ys.size}"
            )
        fx, fy = _finite_pairs(xs, ys)
        if fx.size == 0:
            continue
        marks.append(
            builder(
                x=fx,
                y=fy,
                name=item["label"],
                color=PALETTE[idx % len(PALETTE)],
            )
        )
    figure = xy.chart(*marks, *_axes(x_label, y_label, False))
    return _publish(figure, panel_id, version)
```

- [ ] **Step 4: Run the tests**

Run: `/home/dan/miniforge3/envs/helao/bin/python -m pytest -q helao/core/tests/test_reflex_plots.py`
Expected: PASS, all of them.

- [ ] **Step 5: Format and commit**

```bash
/home/dan/miniforge3/envs/helao/bin/black helao/core/servers/reflex/plots.py helao/core/tests/test_reflex_plots.py
git add helao/core/servers/reflex/plots.py helao/core/tests/test_reflex_plots.py
git commit -m "feat(reflex): add plots.traces for independently-x'd traces

Every existing facade entry assumes one x shared across all series. The data
browser overlays datasets read from unrelated files, each with its own x
column, so a shared axis would silently misalign them."
```

---

### Task 2: Index cache, scan and filter

**Files:**
- Create: `helao/core/servers/data_browser/app_reflex.py`
- Test: `helao/core/tests/test_reflex_data_browser.py`

**Interfaces:**
- Consumes: `sources.GROUPS`, `sources.get_index`, `app.INDEX_TABLE_COLS`, `app.FILTER_COLS` — **read from `sources` and `app` as imports, do not restate the column lists.** A second copy drifts.
- Produces: `IndexCache` (`put`/`get`/`drop`), and the module-level helpers `options_for_group(group) -> list`, `scan_index(root, source, date_start, date_end) -> (df|None, error_str)`, `filter_index(df|None, query) -> df|None`, `index_rows(df|None) -> list[list[str]]`, `cap_rows(rows, cap) -> (view, total, truncated)`. Tasks 3 and 4 build on these. `BrowserState` itself arrives in Task 4.

**Why the cache:** the index is thousands of rows of bulk data. It must not ride a Reflex var (parent spec, Decision 8), and it must be per-session so two tabs scanning different sources do not overwrite each other.

- [ ] **Step 1: Write the failing tests**

Create `helao/core/tests/test_reflex_data_browser.py`:

```python
"""Tests for the Reflex data browser page.

State transitions are driven directly. Reflex state cannot be instantiated
outside an app, so the page's logic lives in module-level functions and a cache
object that these exercise without app machinery -- the same split that let the
visualiser panels be tested at all.
"""

import json
import os

import pytest

from helao.core.servers.data_browser import app_reflex as dbx


def _write_hlo(path):
    """Minimal HLO file: YAML header, %% marker, JSONL body."""
    with open(path, "w") as fh:
        fh.write("hlo_version: 1.0\n")
        fh.write("action_name: cv\n")
        fh.write("column_headings: [t_s, Ewe_V]\n")
        fh.write("%%\n")
        fh.write(json.dumps({"t_s": 0.0, "Ewe_V": 0.1}) + "\n")
        fh.write(json.dumps({"t_s": 1.0, "Ewe_V": 0.2}) + "\n")


@pytest.fixture
def run_tree(tmp_path):
    """A RUNS_FINISHED tree with one sequence, one experiment, one hlo file."""
    import yaml

    day = tmp_path / "RUNS_FINISHED" / "26.30" / "0801"
    seq = day / "120000__seq--cv__label"
    exp = seq / "260801.120000__exp--cv"
    act = exp / "0__0__PSTAT__cv"
    act.mkdir(parents=True)
    with open(seq / "260801.120000000000-seq.yml", "w") as fh:
        yaml.safe_dump({"sequence_name": "cv", "run_type": "test"}, fh)
    with open(exp / "260801.120000000000-exp.yml", "w") as fh:
        yaml.safe_dump({"experiment_name": "cv"}, fh)
    with open(act / "260801.120000000000-act.yml", "w") as fh:
        yaml.safe_dump({"action_name": "cv", "technique_name": "cv"}, fh)
    _write_hlo(str(act / "cv_data.hlo"))
    return str(tmp_path)


def test_source_options_follow_the_selected_group():
    from helao.core.servers.data_browser import sources

    assert dbx.options_for_group("RUNS") == sources.GROUPS["RUNS"]
    assert dbx.options_for_group("DERIVED") == sources.GROUPS["DERIVED"]


def test_options_for_an_unknown_group_is_empty_not_an_error():
    """A stale group string from a reconnecting session must not 500 the page."""
    assert dbx.options_for_group("NOPE") == []


def test_scan_index_returns_rows_for_a_real_tree(run_tree):
    df, error = dbx.scan_index(run_tree, "RUNS_FINISHED", None, None)
    assert error == ""
    assert len(df) == 1
    assert df.iloc[0]["file_name"] == "cv_data.hlo"


def test_scan_index_reports_a_bad_source_instead_of_raising(run_tree):
    """The Bokeh app catches this and writes it to a status line; a raised
    exception inside a Reflex background event just vanishes into the log."""
    df, error = dbx.scan_index(run_tree, "NOT_A_SOURCE", None, None)
    assert df is None
    assert "NOT_A_SOURCE" in error


def test_scan_index_on_an_empty_root_is_empty_not_an_error(tmp_path):
    df, error = dbx.scan_index(str(tmp_path), "RUNS_FINISHED", None, None)
    assert error == ""
    assert len(df) == 0


def test_filter_matches_across_every_filter_column(run_tree):
    df, _ = dbx.scan_index(run_tree, "RUNS_FINISHED", None, None)
    assert len(dbx.filter_index(df, "cv")) == 1
    assert len(dbx.filter_index(df, "PSTAT")) == 1
    assert len(dbx.filter_index(df, "zzzz")) == 0


def test_filter_is_case_insensitive(run_tree):
    df, _ = dbx.scan_index(run_tree, "RUNS_FINISHED", None, None)
    assert len(dbx.filter_index(df, "CV")) == 1


def test_empty_filter_returns_everything(run_tree):
    df, _ = dbx.scan_index(run_tree, "RUNS_FINISHED", None, None)
    assert len(dbx.filter_index(df, "   ")) == len(df)


def test_filter_on_no_index_is_empty(run_tree):
    assert dbx.filter_index(None, "cv") is None


def test_index_rows_are_strings_for_the_table(run_tree):
    """Reflex serialises state to JSON; a numpy bool or NaN in a table cell
    renders as garbage or breaks the encoder."""
    df, _ = dbx.scan_index(run_tree, "RUNS_FINISHED", None, None)
    rows = dbx.index_rows(df)
    assert rows and all(isinstance(c, str) for c in rows[0])


def test_cap_rows_passes_a_short_list_through():
    rows = [["a"], ["b"]]
    view, total, truncated = dbx.cap_rows(rows, 10)
    assert view == rows and total == 2 and truncated is False


def test_cap_rows_reports_that_it_capped():
    """A silent truncation reads as 'this is everything' when it is not."""
    rows = [[str(i)] for i in range(20)]
    view, total, truncated = dbx.cap_rows(rows, 5)
    assert len(view) == 5 and total == 20 and truncated is True


def test_cache_is_per_session():
    cache = dbx.IndexCache()
    cache.put("tok-a", "df-a")
    cache.put("tok-b", "df-b")
    assert cache.get("tok-a") == "df-a"
    assert cache.get("tok-b") == "df-b"


def test_cache_returns_none_for_an_unknown_session():
    assert dbx.IndexCache().get("nobody") is None


def test_cache_drop_frees_a_session():
    cache = dbx.IndexCache()
    cache.put("tok", "df")
    cache.drop("tok")
    assert cache.get("tok") is None
```

- [ ] **Step 2: Run them and watch them fail**

Run: `/home/dan/miniforge3/envs/helao/bin/python -m pytest -q helao/core/tests/test_reflex_data_browser.py`
Expected: FAIL at import, `ModuleNotFoundError: ... app_reflex`

- [ ] **Step 3: Create `app_reflex.py` with the cache and scan/filter helpers**

```python
"""Reflex rendering of the data browser.

A second UI over the same logic the Bokeh browser uses: ``sources`` builds the
index, ``state`` turns index rows into datasets, traces and summary rows, and
``readers`` reads files. None of those modules know this exists, and none of
them may be changed to suit it -- ``app.py`` is still live beside this.

The parts that can be wrong live in module-level functions rather than on the
state class, because ``rx.State`` cannot be instantiated outside a running app.
The state class is then only var assignment and cadence.
"""

__all__ = [
    "IndexCache",
    "INDEX_CACHE",
    "BrowserState",
    "build_page",
    "options_for_group",
    "scan_index",
    "filter_index",
    "index_rows",
    "cap_rows",
]

import threading

import reflex as rx

from helao.core.servers.data_browser import sources
from helao.core.servers.data_browser import state as dbstate
from helao.core.servers.data_browser.app import FILTER_COLS, INDEX_TABLE_COLS
from helao.core.servers.reflex import plots
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Trailing points kept per trace. Mirrors the Bokeh browser's `max_points`
#: server param default.
DEFAULT_MAX_POINTS = 50000

#: Index rows rendered at once. The checkbox table is one component per cell,
#: so a several-thousand-row scan would build a browser-hostile DOM. The page
#: says when it has capped, rather than quietly showing a prefix.
MAX_INDEX_ROWS = 500


class IndexCache:
    """Process-side ``session_token -> index DataFrame`` map.

    The index runs to thousands of rows: bulk data, which the parent spec keeps
    off Reflex's JSON state channel. It is keyed per session so two tabs
    scanning different sources cannot overwrite each other.
    """

    def __init__(self):
        """Create an empty cache."""
        self._lock = threading.Lock()
        self._frames: dict = {}

    def put(self, token: str, df) -> None:
        """Store the newest scan for a session."""
        with self._lock:
            self._frames[token] = df

    def get(self, token: str):
        """Return a session's scan, or ``None`` if it has not scanned."""
        with self._lock:
            return self._frames.get(token)

    def drop(self, token: str) -> None:
        """Forget a session, e.g. when its page unmounts."""
        with self._lock:
            self._frames.pop(token, None)


#: Process-wide cache the page reads through.
INDEX_CACHE = IndexCache()


def options_for_group(group: str) -> list:
    """Source names in a group.

    Args:
        group: Key of :data:`sources.GROUPS`.

    Returns:
        list: Source names, empty for an unknown group. Empty rather than
        raising: a reconnecting session can carry a stale group string, and a
        500 on the page is a worse answer than an empty select.
    """
    return list(sources.GROUPS.get(group, []))


def scan_index(root: str, source: str, date_start, date_end):
    """Build the candidate-dataset index.

    Args:
        root: HELAO output root.
        source: Source name.
        date_start: ``YY.WW/MMDD`` lower bound, or ``None``.
        date_end: Upper bound, or ``None``.

    Returns:
        tuple: ``(DataFrame, "")`` on success, ``(None, message)`` on failure.
        Failures are returned rather than raised: this runs inside a background
        event, where an exception is swallowed into the log and the page just
        sits there looking like a hang.
    """
    try:
        return sources.get_index(root, source, date_start, date_end), ""
    except Exception as exc:
        LOGGER.warning(f"data browser scan failed for {source!r}: {exc}")
        return None, f"scan failed for {source}: {exc}"


def filter_index(index_df, query: str):
    """Filter the index by a substring across :data:`FILTER_COLS`.

    Args:
        index_df: The scanned index, or ``None``.
        query: Free-text query; blank returns everything.

    Returns:
        The filtered DataFrame, or ``None`` when there is no index.
    """
    if index_df is None:
        return None
    needle = (query or "").strip().lower()
    if not needle:
        return index_df
    mask = (
        index_df[FILTER_COLS]
        .astype(str)
        .apply(lambda r: needle in " ".join(r.values).lower(), axis=1)
    )
    return index_df[mask]


def index_rows(index_df) -> list:
    """Render the index as table rows.

    Every cell is a string: Reflex serialises state to JSON, and a numpy bool
    or a NaN reaches the browser as garbage or breaks the encoder outright.

    Args:
        index_df: A scanned (and possibly filtered) index, or ``None``.

    Returns:
        list[list[str]]: One row per dataset, columns in
        :data:`INDEX_TABLE_COLS` order.
    """
    if index_df is None or not len(index_df):
        return []
    return [
        [str(row[col]) for col in INDEX_TABLE_COLS]
        for _, row in index_df.iterrows()
    ]


def cap_rows(rows: list, cap: int):
    """Limit rendered rows, reporting whether anything was withheld.

    Args:
        rows: All matching rows.
        cap: Maximum to render.

    Returns:
        tuple: ``(view, total, truncated)``. The caller shows ``total`` and
        ``truncated`` -- a capped table that does not say so reads as the whole
        result set.
    """
    return rows[:cap], len(rows), len(rows) > cap
```

- [ ] **Step 4: Run the tests**

Run: `/home/dan/miniforge3/envs/helao/bin/python -m pytest -q helao/core/tests/test_reflex_data_browser.py`
Expected: PASS. `BrowserState` and `build_page` do not exist yet; nothing here references them.

- [ ] **Step 5: Format and commit**

```bash
/home/dan/miniforge3/envs/helao/bin/black helao/core/servers/data_browser/app_reflex.py helao/core/tests/test_reflex_data_browser.py
git add helao/core/servers/data_browser/app_reflex.py helao/core/tests/test_reflex_data_browser.py
git commit -m "feat(browser): index cache plus scan and filter for the Reflex page

The index is bulk data, so it lives in a per-session process cache rather than
a Reflex var. Scan failures are returned, not raised: inside a background event
an exception is swallowed into the log and the page looks like a hang."
```

---

### Task 3: Selection, chart and tables

**Files:**
- Modify: `helao/core/servers/data_browser/app_reflex.py`
- Test: `helao/core/tests/test_reflex_data_browser.py`

**Interfaces:**
- Consumes: Task 1's `plots.traces`; Task 2's `filter_index`; `dbstate.load_selected`, `dbstate.available_columns`, `dbstate.build_trace`, `dbstate.downsample`, `dbstate.summary_row`, `dbstate.SUMMARY_COLS`.
- Produces: `load_positions(index_df, positions)`, `axis_options(selected)`, `chart_series(selected, xcol, ycol, max_points)`, `summary_rows(selected, xcol, ycol)`, `dataset_rows(ds)`. Task 4 wires these to widgets.

- [ ] **Step 1: Write the failing tests**

Append to `helao/core/tests/test_reflex_data_browser.py`:

```python
def _one_dataset(run_tree):
    df, _ = dbx.scan_index(run_tree, "RUNS_FINISHED", None, None)
    selected, skipped = dbx.load_positions(df, [0])
    return selected, skipped


def test_load_positions_reads_the_chosen_rows(run_tree):
    selected, skipped = _one_dataset(run_tree)
    assert len(selected) == 1
    assert skipped == []
    assert "t_s" in selected[0].data


def test_load_positions_reports_skips_rather_than_dropping_them(run_tree):
    """A file that is missing or unreadable is the most common thing a user
    hits; silently omitting it from the plot is the worst presentation."""
    df, _ = dbx.scan_index(run_tree, "RUNS_FINISHED", None, None)
    df = df.copy()
    df.loc[0, "available"] = False
    selected, skipped = dbx.load_positions(df, [0])
    assert selected == []
    assert len(skipped) == 1 and "not available" in skipped[0][1]


def test_load_positions_with_no_index_is_empty(run_tree):
    assert dbx.load_positions(None, [0]) == ([], [])


def test_axis_options_are_the_union_of_dataset_columns(run_tree):
    selected, _ = _one_dataset(run_tree)
    assert dbx.axis_options(selected) == ["Ewe_V", "t_s"]


def test_axis_options_with_nothing_selected_is_empty():
    assert dbx.axis_options([]) == []


def test_chart_series_builds_one_entry_per_dataset(run_tree):
    selected, _ = _one_dataset(run_tree)
    series = dbx.chart_series(selected, "t_s", "Ewe_V", 50000)
    assert len(series) == 1
    assert series[0]["label"] == selected[0].label
    assert len(series[0]["x"]) == 2


def test_chart_series_skips_a_dataset_missing_the_chosen_column(run_tree):
    """Overlaying datasets from unrelated files means some will not share
    columns; that is normal, not an error."""
    selected, _ = _one_dataset(run_tree)
    assert dbx.chart_series(selected, "t_s", "not_a_column", 50000) == []


def test_chart_series_downsamples_to_max_points(run_tree):
    selected, _ = _one_dataset(run_tree)
    ds = selected[0]
    ds.data["t_s"] = list(range(1000))
    ds.data["Ewe_V"] = list(range(1000))
    series = dbx.chart_series([ds], "t_s", "Ewe_V", 10)
    assert len(series[0]["x"]) <= 11


def test_chart_series_with_no_axes_chosen_is_empty(run_tree):
    selected, _ = _one_dataset(run_tree)
    assert dbx.chart_series(selected, "", "", 50000) == []


def test_summary_rows_match_the_shared_summary_columns(run_tree):
    from helao.core.servers.data_browser import state as dbstate

    selected, _ = _one_dataset(run_tree)
    rows = dbx.summary_rows(selected, "t_s", "Ewe_V")
    assert len(rows) == 1
    assert len(rows[0]) == len(dbstate.SUMMARY_COLS)
    assert all(isinstance(c, str) for c in rows[0])


def test_dataset_rows_returns_headers_and_string_cells(run_tree):
    selected, _ = _one_dataset(run_tree)
    headers, rows = dbx.dataset_rows(selected[0])
    assert headers == ["t_s", "Ewe_V"] or headers == ["Ewe_V", "t_s"]
    assert rows and all(isinstance(c, str) for c in rows[0])


def test_dataset_rows_on_nothing_is_empty():
    assert dbx.dataset_rows(None) == ([], [])
```

- [ ] **Step 2: Run them and watch them fail**

Run: `/home/dan/miniforge3/envs/helao/bin/python -m pytest -q helao/core/tests/test_reflex_data_browser.py -k "load_positions or axis_options or chart_series or summary_rows or dataset_rows"`
Expected: FAIL, `AttributeError: module ... has no attribute 'load_positions'`

- [ ] **Step 3: Implement the selection helpers**

Add to `helao/core/servers/data_browser/app_reflex.py`, and extend `__all__` with `"load_positions"`, `"axis_options"`, `"chart_series"`, `"summary_rows"`, `"dataset_rows"`:

```python
def load_positions(index_df, positions):
    """Read the chosen index rows into datasets.

    Args:
        index_df: A scanned (and possibly filtered) index, or ``None``.
        positions: Integer positions into ``index_df``.

    Returns:
        tuple: ``(datasets, skipped)``, where ``skipped`` is
        ``[(label, reason)]``. Unreadable and unavailable files are reported,
        never silently dropped.
    """
    if index_df is None:
        return [], []
    return dbstate.load_selected(index_df.reset_index(drop=True), positions)


def axis_options(selected) -> list:
    """Column names available across the selected datasets."""
    return dbstate.available_columns(selected)


def chart_series(selected, xcol: str, ycol: str, max_points: int) -> list:
    """Build :func:`plots.traces` input from the selected datasets.

    Args:
        selected: ``SelectedDataset`` list.
        xcol: Chosen x column.
        ycol: Chosen y column.
        max_points: Downsampling cap per trace.

    Returns:
        list: ``{"label", "x", "y"}`` per dataset that has both columns.
        Datasets missing either are skipped -- overlaying files from unrelated
        runs means some will not share columns, which is normal.
    """
    if not xcol or not ycol:
        return []
    series = []
    for ds in selected:
        trace = dbstate.build_trace(ds, xcol, ycol)
        if trace is None:
            continue
        trace = dbstate.downsample(trace, max_points)
        series.append({"label": ds.label, "x": trace["x"], "y": trace["y"]})
    return series


def summary_rows(selected, xcol: str, ycol: str) -> list:
    """One summary-table row per selected dataset, as strings."""
    return [
        [str(dbstate.summary_row(ds, xcol, ycol)[col]) for col in dbstate.SUMMARY_COLS]
        for ds in selected
    ]


def dataset_rows(ds):
    """Render one dataset's raw columns as a table.

    Args:
        ds: A ``SelectedDataset``, or ``None``.

    Returns:
        tuple: ``(headers, rows)``, both empty when ``ds`` is ``None``.
    """
    if ds is None:
        return [], []
    headers = list(ds.data.keys())
    if not headers:
        return [], []
    length = min(len(ds.data[h]) for h in headers)
    return headers, [
        [str(ds.data[h][i]) for h in headers] for i in range(length)
    ]
```

- [ ] **Step 4: Run the tests**

Run: `/home/dan/miniforge3/envs/helao/bin/python -m pytest -q helao/core/tests/test_reflex_data_browser.py`
Expected: PASS, all of them.

- [ ] **Step 5: Format and commit**

```bash
/home/dan/miniforge3/envs/helao/bin/black helao/core/servers/data_browser/app_reflex.py helao/core/tests/test_reflex_data_browser.py
git add helao/core/servers/data_browser/app_reflex.py helao/core/tests/test_reflex_data_browser.py
git commit -m "feat(browser): selection, chart series and summary tables

Every helper is module-level and takes plain arguments, so the logic that can
be wrong is reachable without Reflex app machinery -- the split that made the
visualiser panels testable at all."
```

---

### Task 4: The page — state class, layout, and route

**Files:**
- Modify: `helao/core/servers/data_browser/app_reflex.py`
- Modify: `helao/core/servers/reflex/app.py`
- Test: `helao/core/tests/test_reflex_routes_e2e.py`

**Interfaces:**
- Consumes: everything from Tasks 1–3; `plots.chart(spec_var, url_var, layout_var, *, height)`.
- Produces: `BrowserState`, `build_page()`. `helao/core/servers/reflex/app.py` calls `build_page()` for `/browser`.

**The two rules this task must not break**, both learned by the panel port:

1. Anything the serving process needs must exist **before** `add_page`. `reflex run --backend-only` never evaluates a page callable, and Reflex registers event handlers at class creation — a state class created inside the callable is invisible to the backend, and every control silently does nothing.
2. `plots.chart(...)` is called **once**, in the layout. The `plots.traces(...)` call belongs in the event handler that assigns `chart_spec`/`chart_url`/`chart_layout`. Calling a facade function in the layout yields a chart that paints once and never updates.

- [ ] **Step 1: Write the failing test**

In `helao/core/tests/test_reflex_routes_e2e.py`, replace nothing; append:

```python
def test_browser_route_is_the_real_page_not_a_stub(reflex_cfg):
    """The stub said the browser was unimplemented. Once it is implemented, a
    passing route test that still renders the stub is worse than no test."""
    from helao.core.servers.data_browser import app_reflex

    from helao.core.servers.reflex.app import build_app

    build_app(reflex_cfg, "UI")
    assert app_reflex.BrowserState.__name__ == "BrowserState"
    assert callable(app_reflex.build_page)


def test_browser_state_handlers_are_registered_without_compiling_pages(reflex_cfg):
    """Same failure mode the panels hit: handlers created inside the lazy
    add_page callable never exist in a --backend-only process, so every
    control on the page silently does nothing."""
    from reflex_base.registry import RegistrationContext

    from helao.core.servers.data_browser.app_reflex import BrowserState
    from helao.core.servers.reflex.app import build_app

    build_app(reflex_cfg, "UI")
    registered = set(RegistrationContext.get().event_handlers)
    # Derived from the class, never hand-spelled: Reflex builds a state's full
    # name from its module path and a snake_cased class name, so a guessed
    # literal would be a test that passes for the wrong reason or fails for no
    # reason.
    prefix = BrowserState.get_full_name()
    for handler in ("scan", "on_filter", "add_selected", "clear_plot"):
        assert (
            f"{prefix}.{handler}" in registered
        ), f"BrowserState.{handler} not registered without page compilation"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `/home/dan/miniforge3/envs/helao/bin/python -m pytest -q helao/core/tests/test_reflex_routes_e2e.py -k browser`
Expected: FAIL, `AttributeError: module ... has no attribute 'BrowserState'`

- [ ] **Step 3: Add the state class and layout**

Append to `helao/core/servers/data_browser/app_reflex.py`:

```python
class BrowserState(rx.State):
    """Page state for the data browser.

    A plain state, not a mixin: mixins exist for ``make_panel_state``, which
    mints one class per action server so their vars cannot be shared. This is
    one page with one state.
    """

    #: Selected datasets. The leading underscore makes this a Reflex *backend*
    #: var: it stays server-side and is never serialised to the client. That is
    #: required, not cosmetic -- these hold whole data files, and an ordinary
    #: annotated attribute would become a client var and fail to encode.
    _datasets: list = []

    group: str = "RUNS"
    source: str = ""
    source_options: list = []
    date_start: str = ""
    date_end: str = ""
    index_filter: str = ""
    index_rows_view: list = []
    selected_positions: list = []
    index_total: int = 0
    index_truncated: bool = False
    status: str = ""
    error: str = ""
    scanning: bool = False
    xcol: str = ""
    ycol: str = ""
    axis_choices: list = []
    trace_kind: str = "line"
    chart_spec: dict = {}
    chart_url: str = ""
    chart_layout: str = ""
    version: int = 0
    summary_view: list = []
    row_headers: list = []
    row_view: list = []

    def panel_key(self) -> str:
        """Session-scoped buffer-store key.

        The store holds one frame per key while ``version`` is per-session
        state, so a shared key would 404 two tabs into frozen charts.
        """
        return f"browser-{self.router.session.client_token}"

    @rx.event
    def on_mount(self):
        """Seed the source options from the default group."""
        self.source_options = options_for_group(self.group)
        if self.source_options and self.source not in self.source_options:
            self.source = self.source_options[0]

    @rx.event
    def on_group(self, value: str):
        """Switch group and reset the source to that group's first entry."""
        self.group = value
        self.source_options = options_for_group(value)
        self.source = self.source_options[0] if self.source_options else ""

    @rx.event
    def on_source(self, value: str):
        """Select the source to scan."""
        self.source = value

    @rx.event
    def on_date_start(self, value: str):
        """Set the lower date bound."""
        self.date_start = value

    @rx.event
    def on_date_end(self, value: str):
        """Set the upper date bound."""
        self.date_end = value

    @rx.event
    def on_trace_kind(self, value: str):
        """Switch between line and scatter."""
        self.trace_kind = value
        self._rebuild()

    @rx.event
    def on_xcol(self, value: str):
        """Choose the x column."""
        self.xcol = value
        self._rebuild()

    @rx.event
    def on_ycol(self, value: str):
        """Choose the y column."""
        self.ycol = value
        self._rebuild()

    @rx.event
    def on_filter(self, value: str):
        """Filter the index table."""
        self.index_filter = value
        self._refresh_index()

    @rx.event(background=True)
    async def scan(self):
        """Index the selected source.

        Background because ``sources.get_index`` walks the run tree, which on a
        station's output root takes long enough to freeze a synchronous handler
        outright.
        """
        async with self:
            self.scanning = True
            self.error = ""
            self.status = f"scanning {self.source}..."
            root = _config_root()
            source, start, end = self.source, self.date_start, self.date_end
            token = self.router.session.client_token

        df, error = scan_index(root, source, start.strip() or None, end.strip() or None)

        async with self:
            self.scanning = False
            if error:
                self.error = error
                self.status = ""
                INDEX_CACHE.drop(token)
                self.index_rows_view = []
                return
            INDEX_CACHE.put(token, df)
            self.status = f"indexed {len(df)} dataset(s) from {source}"
            self.selected_positions = []
            self._refresh_index()

    @rx.event(background=True)
    async def add_selected(self):
        """Load the checked index rows and add them to the plot.

        Background because each dataset is a file read.
        """
        async with self:
            token = self.router.session.client_token
            positions = list(self.selected_positions)
            query = self.index_filter
        df = filter_index(INDEX_CACHE.get(token), query)
        datasets, skipped = load_positions(df, positions)

        async with self:
            self._datasets.extend(datasets)
            if skipped:
                # Named, not silently dropped: an omitted trace with no
                # explanation is the worst way to present an unreadable file.
                self.error = "; ".join(f"skipped {lbl}: {why}" for lbl, why in skipped)
            self._refresh_axes()
            self._rebuild()

    @rx.event
    def clear_plot(self):
        """Drop every selected dataset."""
        self._datasets = []
        self.error = ""
        self._refresh_axes()
        self._rebuild()

    @rx.event
    def on_unmount(self):
        """Release this session's index and chart frame."""
        token = self.router.session.client_token
        INDEX_CACHE.drop(token)
        plots.STORE.drop(f"browser-{token}")

    @rx.event
    def toggle_position(self, position: int):
        """Check or uncheck one index row.

        Reflex's data_table has no row-selection callback, so selection is an
        explicit checkbox column rather than a table feature. Positions index
        into the *filtered* frame, which is what ``load_positions`` takes.
        """
        if position in self.selected_positions:
            self.selected_positions = [
                p for p in self.selected_positions if p != position
            ]
        else:
            self.selected_positions = self.selected_positions + [position]

    # -- internals -------------------------------------------------------

    def _refresh_index(self):
        """Re-render the index table under the current filter."""
        token = self.router.session.client_token
        filtered = filter_index(INDEX_CACHE.get(token), self.index_filter)
        view, total, truncated = cap_rows(index_rows(filtered), MAX_INDEX_ROWS)
        self.index_rows_view = view
        self.index_total = total
        self.index_truncated = truncated
        # Positions index into the filtered frame, so a changed filter
        # invalidates every one of them; keeping them would add whichever rows
        # now happen to sit at those offsets.
        self.selected_positions = []

    def _refresh_axes(self):
        """Recompute axis choices, keeping the current pick when still valid."""
        self.axis_choices = axis_options(self._datasets)
        if not self.axis_choices:
            self.xcol, self.ycol = "", ""
            return
        if self.xcol not in self.axis_choices:
            self.xcol = self.axis_choices[0]
        if self.ycol not in self.axis_choices:
            self.ycol = (
                self.axis_choices[1]
                if len(self.axis_choices) > 1
                else self.axis_choices[0]
            )

    def _rebuild(self):
        """Recompute the chart payload and the summary table."""
        series = chart_series(self._datasets, self.xcol, self.ycol, DEFAULT_MAX_POINTS)
        self.version += 1
        payload = plots.traces(
            series,
            kind=self.trace_kind,
            x_label=self.xcol,
            y_label=self.ycol,
            panel_id=self.panel_key(),
            version=self.version,
        )
        self.chart_spec = payload.spec
        self.chart_url = payload.buffer_url
        self.chart_layout = payload.layout
        self.summary_view = summary_rows(self._datasets, self.xcol, self.ycol)
        self.status = f"{len(self._datasets)} dataset(s) selected"


def _config_root() -> str:
    """HELAO output root from the installed global config."""
    from helao.helpers import config_loader

    cfg = config_loader.CONFIG or {}
    return str(cfg.get("root", ""))


def build_page():
    """Render the data browser page.

    Returns:
        rx.Component: The page body.
    """
    controls = rx.hstack(
        rx.select(
            list(sources.GROUPS.keys()),
            value=BrowserState.group,
            on_change=BrowserState.on_group,
            width="9em",
        ),
        rx.select(
            BrowserState.source_options,
            value=BrowserState.source,
            on_change=BrowserState.on_source,
            width="12em",
        ),
        rx.input(
            placeholder="From (YY.WW/MMDD)",
            value=BrowserState.date_start,
            on_change=BrowserState.on_date_start,
            width="11em",
        ),
        rx.input(
            placeholder="To (YY.WW/MMDD)",
            value=BrowserState.date_end,
            on_change=BrowserState.on_date_end,
            width="11em",
        ),
        rx.button(
            "Scan",
            on_click=BrowserState.scan,
            loading=BrowserState.scanning,
        ),
        spacing="3",
        align="end",
        width="100%",
    )

    # An explicit checkbox column, not rx.data_table: gridjs exposes no
    # row-selection callback, and the Bokeh browser's whole workflow is
    # "tick several rows, then Add to plot". A read-only table would strand it.
    index_box = rx.vstack(
        rx.input(
            placeholder="Filter index",
            value=BrowserState.index_filter,
            on_change=BrowserState.on_filter,
            width="100%",
        ),
        rx.cond(
            BrowserState.index_truncated,
            rx.text(
                f"showing the first {MAX_INDEX_ROWS} of ",
                BrowserState.index_total,
                " matches — narrow the filter to reach the rest",
                size="2",
                color_scheme="amber",
            ),
        ),
        rx.scroll_area(
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell(""),
                        *[
                            rx.table.column_header_cell(col)
                            for col in INDEX_TABLE_COLS
                        ],
                    )
                ),
                rx.table.body(
                    rx.foreach(
                        BrowserState.index_rows_view,
                        lambda row, idx: rx.table.row(
                            rx.table.cell(
                                rx.checkbox(
                                    checked=BrowserState.selected_positions.contains(
                                        idx
                                    ),
                                    on_change=lambda _: BrowserState.toggle_position(
                                        idx
                                    ),
                                )
                            ),
                            rx.foreach(row, lambda cell: rx.table.cell(cell)),
                        ),
                    )
                ),
                width="100%",
                size="1",
            ),
            type="auto",
            scrollbars="vertical",
            height="20em",
        ),
        rx.hstack(
            rx.button("Add to plot", on_click=BrowserState.add_selected),
            rx.button("Clear plot", on_click=BrowserState.clear_plot),
            spacing="3",
        ),
        width="100%",
        spacing="2",
    )

    plot_tab = rx.vstack(
        rx.hstack(
            rx.select(
                BrowserState.axis_choices,
                value=BrowserState.xcol,
                on_change=BrowserState.on_xcol,
                width="12em",
            ),
            rx.select(
                BrowserState.axis_choices,
                value=BrowserState.ycol,
                on_change=BrowserState.on_ycol,
                width="12em",
            ),
            rx.select(
                list(plots.TRACE_KINDS),
                value=BrowserState.trace_kind,
                on_change=BrowserState.on_trace_kind,
                width="9em",
            ),
            spacing="3",
        ),
        # Bound once. The payload is produced in _rebuild, per tick.
        plots.chart(
            BrowserState.chart_spec,
            BrowserState.chart_url,
            BrowserState.chart_layout,
            height=420,
        ),
        width="100%",
        spacing="3",
    )

    table_tab = rx.data_table(
        data=BrowserState.summary_view,
        columns=list(dbstate.SUMMARY_COLS),
        pagination=True,
        search=False,
        sort=True,
    )

    return rx.vstack(
        controls,
        rx.cond(BrowserState.error != "", rx.text(BrowserState.error, color_scheme="red")),
        rx.text(BrowserState.status, size="2"),
        index_box,
        rx.tabs.root(
            rx.tabs.list(
                rx.tabs.trigger("Plot", value="plot"),
                rx.tabs.trigger("Table", value="table"),
            ),
            rx.tabs.content(plot_tab, value="plot"),
            rx.tabs.content(table_tab, value="table"),
            default_value="plot",
            width="100%",
        ),
        width="100%",
        spacing="4",
        padding_x="1em",
        on_mount=BrowserState.on_mount,
        on_unmount=BrowserState.on_unmount,
    )
```

- [ ] **Step 4: Wire the route**

In `helao/core/servers/reflex/app.py`, replace the `/browser` `add_page` call:

```python
    application.add_page(
        lambda: _page("Data browser", build_page()),
        route="/browser",
        title="HELAO browser",
    )
```

Add the import at the top of `build_app`'s module:

```python
from helao.core.servers.data_browser.app_reflex import BrowserState, build_page
```

and, immediately before the `add_page` calls (beside `_ensure_panel_states(routes)`), force the state class into existence for the backend-only process:

```python
    # Same reason as _ensure_panel_states: add_page's callable is lazy and
    # `reflex run --backend-only` never evaluates it, so a state class first
    # touched inside it would never be created — and Reflex registers event
    # handlers at class creation. Referencing it here is what registers them.
    assert BrowserState is not None
```

- [ ] **Step 5: Run the tests**

Run: `/home/dan/miniforge3/envs/helao/bin/python -m pytest -q helao/core/tests/test_reflex_routes_e2e.py`
Expected: PASS, including both new browser tests.

Run: `/home/dan/miniforge3/envs/helao/bin/python -m pytest -q helao/core/tests/test_reflex_data_browser.py helao/core/tests/test_reflex_plots.py helao/core/tests/test_reflex_config.py`
Expected: PASS.

- [ ] **Step 6: Format and commit**

```bash
/home/dan/miniforge3/envs/helao/bin/black helao/core/servers/data_browser/app_reflex.py helao/core/servers/reflex/app.py helao/core/tests/test_reflex_routes_e2e.py
git add helao/core/servers/data_browser/app_reflex.py helao/core/servers/reflex/app.py helao/core/tests/test_reflex_routes_e2e.py
git commit -m "feat(browser): Reflex data browser page on /browser

Replaces the stub route. The state class is referenced at build time rather
than only inside add_page's lazy callable: --backend-only never evaluates that
callable, and Reflex registers event handlers at class creation, so every
control would silently do nothing."
```

---

### Task 5: Verify it renders

**Files:**
- Create: `helao/core/tests/browser_check_data_browser.py` (a script, not a pytest module — it needs a launched group)
- Modify: `CLAUDE.md`

**Why a task and not a manual step:** the parent port shipped six rendering defects past a green unit suite because nothing loaded a page. Playwright and headless chromium are installed in the `helao` conda env.

- [ ] **Step 1: Rebuild the frontend bundle**

The page is compiled into the bundle, so a new route needs a rebuild. `/mnt/STORAGE` is mounted `noexec`, so the build must be staged somewhere executable:

```bash
STAGE=/tmp/reflex-build-browser
rm -rf "$STAGE" && mkdir -p "$STAGE"
cp -r helao/core/servers/reflex/_app "$STAGE/_app"
rm -rf "$STAGE/_app/.web" "$STAGE/_app/assets" "$STAGE/_app/frontend.zip"
cd "$STAGE/_app"
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async \
  conda run -n helao python -c \
  "from helao.core.servers.reflex.xy_component import copy_client_asset; copy_client_asset('$STAGE/_app/assets')"
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async HELAO_REFLEX_CONFIG=goldenreflex \
  HELAO_REFLEX_SERVER_KEY=UI conda run -n helao reflex init --name helao_ui --no-agents
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async HELAO_REFLEX_CONFIG=goldenreflex \
  HELAO_REFLEX_SERVER_KEY=UI conda run -n helao reflex export --frontend-only
cd /mnt/STORAGE/repos/helao/helao-async
rm -rf .reflex-bundle/helao_ui && mkdir -p .reflex-bundle/helao_ui
cd .reflex-bundle/helao_ui && unzip -q "$STAGE/_app/frontend.zip"
```

Expected: `browser.html` present in `.reflex-bundle/helao_ui/`.

- [ ] **Step 2: Write the check**

Create `helao/core/tests/browser_check_data_browser.py`:

```python
"""Headless check of the Reflex data browser against a running group.

Not a pytest module: it needs a launched orchestration group. Run it after
`python launch.py goldenreflex`:

    /home/dan/miniforge3/envs/helao/bin/python \
        helao/core/tests/browser_check_data_browser.py
"""

import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5010"


def main() -> int:
    """Scan, select, plot, and assert the chart actually painted."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)[:300]))
        page.on(
            "console",
            lambda m: errors.append(m.text[:200]) if m.type == "error" else None,
        )

        page.goto(f"{BASE}/browser", wait_until="load", timeout=60000)
        page.wait_for_timeout(3000)

        page.get_by_role("button", name="Scan").click()
        # The scan walks the run tree; give it room without hiding a hang.
        page.wait_for_timeout(15000)
        body = page.inner_text("body")

        problems = []
        if "indexed" not in body and "scan failed" not in body:
            problems.append("scan produced neither an index nor an error")
        if "scan failed" in body:
            problems.append(f"scan failed: {body[:200]}")
        if errors:
            problems.append(f"page errors: {errors[:5]}")

        # xy emits an accessibility summary; it is the cheapest proof of paint.
        if "Interactive chart" not in body:
            problems.append("no chart rendered")

        browser.close()

    if problems:
        print("FAIL: " + "; ".join(problems))
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Launch a group and run it**

`launch.py` spawns children via `PATH` python and needs a tty for its hotkey thread:

```bash
PATH=/home/dan/miniforge3/envs/helao/bin:$PATH \
PYTHONPATH=/mnt/STORAGE/repos/helao/helao-async \
  script -qfec "python -u launch.py goldenreflex --no-hot-reload" /dev/null > /tmp/group.log 2>&1 &
# wait for 5010, 5011, 8001-8004, 5001 to listen, then:
/home/dan/miniforge3/envs/helao/bin/python helao/core/tests/browser_check_data_browser.py
```

Expected: `PASS`.

If the page renders but every control does nothing, the backend is missing the state class — check `/tmp/group.log` for `No registered handler found for event`, and confirm Task 4 Step 4 landed.

- [ ] **Step 4: Document the page**

In `CLAUDE.md`, under the Reflex UI stack section, after the bullet about the plot facade's two call sites, add:

```markdown
- **The data browser has two UIs over one logic layer.** `helao/core/servers/data_browser/{readers,state,sources}.py` are backend-agnostic and shared; `app.py` is the Bokeh document and `app_reflex.py` is the Reflex page on `/browser`. Never fork behaviour into one UI — add it to the shared layer so the other keeps working.
```

- [ ] **Step 5: Commit**

```bash
/home/dan/miniforge3/envs/helao/bin/black helao/core/tests/browser_check_data_browser.py
git add helao/core/tests/browser_check_data_browser.py CLAUDE.md
git commit -m "test(browser): headless render check for the Reflex data browser

The parent port shipped six rendering defects past a green unit suite because
nothing loaded a page. This scans, plots, and asserts xy actually painted."
```

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-02-reflex-data-browser.md`. Two execution options:

**1. Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session with checkpoints for review.

Which approach?
