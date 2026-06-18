# Data Browser Visualizer — Design Spec

**Date:** 2026-06-18
**Status:** Approved (design); pending implementation plan
**Author:** Dan Guevarra (with Claude Code)

## Summary

A new Bokeh visualizer server for HELAO-async that browses **finished/derived data on
disk** (post-hoc), as opposed to the existing visualizers which are all live WebSocket
subscribers. It lets a user filter and select datasets from four sources, overlay
arbitrary datasets on a shared plot with free axis assignment, and inspect the plotted
data in a linked, filterable table.

It is enabled per-config like any other visualizer (`group: visualizer`,
`bokeh: data_browser`).

## Goals

- Browse and filter data from `PROCESSES`, `ANALYSES`, `RUNS_SYNCED` (zipped and
  unzipped sequences), and `RUNS_FINISHED`.
- Overlay "similar" data from different entities on one plot, where the user freely
  assigns any column to the X and Y axes (no enforced technique/key matching).
- Provide a filterable table view of the plotted data, with both a per-trace summary
  and the underlying data rows.
- Stay responsive against large `RUNS_*` trees (thousands of sequences).
- Read **local files only** — no S3/cloud credentials required in the visualizer.

## Non-goals

- No live/streaming data (that is what the existing `*_vis.py` subscribers do).
- No S3 fetching. Analysis outputs that exist only in S3 are shown but not plotted.
- No cross-source schema normalization into a single unified index. Sources are grouped
  (see below), not merged.
- No editing/writing of data — read-only browser.

## User decisions captured during brainstorming

1. **Navigation:** Two source *groups* feeding one shared plot+table — RUNS group
   (`RUNS_FINISHED` + `RUNS_SYNCED`) and DERIVED group (`PROCESSES` + `ANALYSES`).
2. **Overlay matching:** Free axis assignment. User maps any column to X/Y; every
   selected dataset that has both columns becomes a trace. No technique/key matching
   enforced.
3. **Leaf unit:** Any column-bearing data file (`.hlo`, `.json`, `.parquet`), not just
   `.hlo` and not capped at action granularity.
4. **Analyses data source:** Local files only. S3-only outputs are greyed/non-selectable.
5. **Table view:** Both, linked — a per-trace summary table on top; selecting a trace
   row reveals that trace's underlying data rows below.
6. **Indexing/scale:** Date-range first. User scopes by the cheap `YY.WW/MMDD` directory
   structure (or a specific sequence dir); only that subset is indexed, deeper levels
   lazy-loaded on expand.
7. **Placement:** Modules under `helao/deploy/hte/servers/visualizer/` and
   `helao/deploy/test/servers/visualizer/`, following existing convention. To avoid
   duplicating a large browser, the heavy logic lives in a shared `helao/core` module
   and each deployment file is a thin `makeBokehApp` shim.
8. **Layout:** Layout "A" — persistent control bar on top, persistent browse/filter index
   on the left, and a **tabbed right region (Plot | Table) that shares one selection
   state**.

## Architecture

### Module layout

- `helao/core/servers/data_browser.py` — all browser logic (index backends, dataset
  reader, Bokeh document construction). Built on `HelaoVis` / `Vis`
  (`helao/core/servers/vis.py`), which provides `world_cfg`, resolved `helaodirs`
  (`root`, `save_root`, `ana_root`, `process_root`), and the shared logger.
- `helao/deploy/hte/servers/visualizer/data_browser.py` — thin shim exposing
  `makeBokehApp(doc, confPrefix, server_key, helao_repo_root)` that delegates to the core
  module.
- `helao/deploy/test/servers/visualizer/data_browser.py` — identical thin shim.

The launcher (`bokeh_launcher.py`) resolves
`helao.deploy.<deployment>.servers.visualizer.data_browser.makeBokehApp` natively, so no
launcher changes are needed.

### Config

Enabled by adding a `visualizer` server entry:

```yaml
  DATABROWSE:
    host: 127.0.0.1
    port: 5003
    group: visualizer
    bokeh: data_browser
    params:
      doc_name: Data Browser
      max_points: 50000        # optional, plotted-point cap before downsampling
      launch_browser: true     # optional
```

## Data access layer

A common `SourceIndex` interface, implemented once per source group, returns:

- `index_df` — a pandas DataFrame describing candidate datasets (one row per
  column-bearing file or selectable record), with columns used for filtering and the
  summary table: `source`, `sequence`, `experiment`, `action`/`process`, `technique`,
  `sample`, `run_type`, `file_name`, `file_type`, `date`, `available` (False when
  S3-only/missing locally), plus an internal locator used by the reader.
- `read_dataset(row) -> (meta: dict, data: dict[str, ndarray])` — load one dataset's
  columns regardless of source/format.

### RUNS group (`RUNS_FINISHED`, `RUNS_SYNCED`)

Wrap the existing `LocalLoader`
(`helao/core/drivers/data/loaders/localfs.py`), which already indexes both unzipped run
trees and synced sequence `.zip` archives and reads `.hlo` members transparently via
`FileMapper` / `read_hlo_bytes`.

Scoping: the user selects a date range; only `RUNS_*/YY.WW/MMDD` subdirectories within
range are globbed and indexed. Deeper levels (experiment/action/file) are populated lazily
when a node is expanded or when the subset is scanned.

### DERIVED group (`PROCESSES`, `ANALYSES`)

- `PROCESSES`: walk `*-prc.yml` under the `PROCESSES` root (date-scoped the same way),
  parse `ProcessModel`, and resolve each process's `files` (FileInfo) to their on-disk
  data files for plotting.
- `ANALYSES`: read local analysis metadata under the `ANALYSES` root and resolve
  `AnalysisOutputModel` outputs that exist **locally** (`.parquet`/`.json`). Outputs whose
  `analysis_output_path` is an S3 locator with no local copy are listed in the index with
  `available = False` and are greyed/non-selectable.

### Dataset reader (extension dispatch)

`read_dataset` dispatches on file extension to produce `{column_name: ndarray}`:

- `.hlo` → existing `read_hlo` / `read_hlo_bytes` (`helao/helpers/hlo_data.py`).
- `.json` → JSON data reader (line-delimited or columnar dict).
- `.parquet` → pyarrow/pandas read.

Exact local file layout under `ANALYSES` and the precise `.json` data shapes are to be
confirmed against real output during implementation; the reader abstraction isolates that
detail behind `read_dataset`.

## Selection state and data flow

Single source of truth: an ordered list of **selected datasets**, each holding
`{source, locator, meta, columns}`. The Plot tab and Table tab both render purely from this
list, so they always agree.

Flow:

1. Pick group (RUNS / DERIVED) → pick source → set date range → **Scan**.
2. Scan indexes the scoped subset into `index_df`; the left filter table renders it.
3. User types in the filter box (matches technique, sample, run_type, action/file name,
   date) and checks rows.
4. **Add selected to plot** loads each checked row via `read_dataset` and appends to the
   selected-datasets list (skipping unavailable rows).
5. X/Y dropdowns are populated from the **union** of columns across all selected datasets.
   Each dataset that contains both the chosen X and Y columns is drawn as one trace.
6. **Clear plot** empties the selected-datasets list.

## UI components (Layout A)

- **Control bar (persistent, top):** group toggle (RUNS / DERIVED), source dropdown,
  date-range start/end inputs, Scan button.
- **Left index (persistent):** text filter box; multiselect Bokeh `DataTable` over
  `index_df`; "Add selected to plot" and "Clear plot" buttons. Unavailable rows greyed.
- **Right region — tabs sharing the selection state:**
  - **Plot tab:** X dropdown, Y dropdown, plot-type toggle (line / scatter), Bokeh
    `figure` with overlaid traces, legend keyed by source/trace, hover tool.
  - **Table tab:** trace-summary `DataTable` (source, sequence/experiment/action,
    technique, sample, file, point count, X range, Y range) — filterable; selecting a
    summary row populates a second `DataTable` showing that trace's underlying data rows
    (index, X, Y, and other columns), filterable/sortable.

## Error handling and performance

- **Unreadable/corrupt file:** caught per dataset; logged via the `Vis` logger; the row is
  flagged in the index and skipped on add. The Bokeh document never crashes.
- **Large traces:** plotted points capped at `params.max_points` (default e.g. 50000) with
  optional uniform downsampling; the Table tab's data-rows view is paginated/capped
  independently.
- **S3-only / missing-locally:** `available = False`; greyed and non-selectable.
- **Empty or oversized date range:** guarded; a warning is shown rather than a long
  blocking scan.

## Testing

- **Automated (standalone script** under `helao/deploy/test/tests/`, matching the repo's
  no-pytest convention): build a small fixture containing an unzipped run tree and a synced
  sequence `.zip`; assert that the RUNS `SourceIndex` produces the expected index rows and
  that `read_dataset` returns the expected columns for `.hlo`, `.json`, and `.parquet`
  inputs. Add a small `PROCESSES`/`ANALYSES` fixture for the DERIVED index.
- **Manual:** launch the `test` deployment with a `DATABROWSE` server entry against
  simulator output; verify scan → filter → add → overlay → table-drilldown end to end.

## Open items to confirm during implementation

- Exact on-disk layout of local `ANALYSES` outputs and which formats appear locally.
- The precise data shape of `.json` data files (line-delimited vs columnar).
- Whether `LocalLoader`'s current indexing can be scoped to a date sub-range cheaply or
  needs a thin date-filtered globbing wrapper.
