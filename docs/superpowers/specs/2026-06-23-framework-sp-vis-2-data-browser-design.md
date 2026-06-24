# Framework SP-VIS-2 — data_browser Re-layer (design)

**Date:** 2026-06-23
**Branch:** `feat/framework-vis-data-browser`
**Cycle:** Operator / data_browser Bokeh UI migration (second sub-project; see
`2026-06-23-framework-sp-vis-1-foundation-design.md` for the cycle decomposition).

## 1. Context

The Bokeh UI migration cycle decided **full port into framework layers** and
decomposed into three sub-projects:

1. **SP-VIS-1 Foundation** — DONE. `app/vis.py` (`Vis`/`HelaoVis`/`makeBokehApp`),
   `adapters/vis_subscriber.py`, `support/helao_dirs.py`.
2. **SP-VIS-2 data_browser** — this spec.
3. **SP-VIS-3 Operator UI** — later; needs framework `app/orch_api.py`.

The legacy data_browser lives in `helao/core/servers/data_browser/` as a 4-module
package that is already cleanly separated:

| Legacy module | Responsibility | Imports |
|---|---|---|
| `state.py` | pure selection/plot/table transforms + `SelectedDataset`; **plus** `load_selected` (the one I/O function — reads files via `readers`) | `readers` |
| `sources.py` | date-scoped filesystem/zip indexers → uniform index DataFrame | pandas, yaml, zipfile, `readers` |
| `readers.py` | extension-dispatched file readers (`.hlo`/`.json`/`.parquet`) | pyarrow, json, zipfile, `helao.helpers.hlo_data.read_hlo_bytes` |
| `app.py` | Bokeh `_UI` + `build_document(vis)` | bokeh, `sources`, `state` |

It is read-only (indexes and reads `RUNS_FINISHED`/`RUNS_DIAG`/`RUNS_SYNCED`/
`PROCESSES`/`ANALYSES`), with no orchestrator dependency.

## 2. Goal & non-goals

**Goal:** Re-layer the data_browser onto the framework domain/adapters/app split,
honoring the boundary contract, standing on the SP-VIS-1 vis foundation, with the
existing test suite ported to pytest. Pure addition.

**Non-goals:**
- Rewiring deploy shims. `deploy/{test,hte}/servers/visualizer/data_browser.py`
  keep importing legacy `core/` modules; cut-over is the deployment-migration cycle.
- Operator UI (SP-VIS-3).
- Any change to legacy `core/servers/data_browser/**` (left running for unmigrated
  deployments).
- Behavior changes to indexing/reading/plotting — this is a relocation + a single
  responsibility split, not a feature change.

## 3. Boundary contract (from master design §3)

- `domain/` — pure; never imports Bokeh, FastAPI, httpx, filesystem, pyarrow,
  pandas-for-I/O, or `adapters/`.
- `adapters/` — implement ports / do I/O; may import pandas, pyarrow, zipfile,
  yaml, and other `adapters/` (e.g. the SP6 hlo loader). May build `domain`/`models`
  objects. Never imported BY `domain/`.
- `app/` — Bokeh wiring; composes domain + adapters.

The AST boundary check (`helao/framework/tests/test_boundaries.py`) must stay green:
`domain/data_browser.py` imports no I/O and no adapters.

## 4. Components

### 4.1 `helao/framework/domain/data_browser.py` (pure)

Ports the **pure** half of `state.py`:

- `SelectedDataset` dataclass (`locator`, `label`, `source`, `sequence`,
  `experiment`, `node`, `technique`, `sample`, `file_name`, `meta`, `data`) with
  the `columns` property.
- `available_columns(selected) -> list[str]` — sorted union of column names.
- `build_trace(ds, xcol, ycol) -> dict | None`.
- `downsample(trace, max_points) -> dict`.
- `summary_row(ds, xcol, ycol) -> dict`.
- `SUMMARY_COLS` constant.

No imports of `readers`, Bokeh, pyarrow, or pandas. (`load_selected` is **removed**
from this module — see §4.4.)

### 4.2 `helao/framework/adapters/data_browser/readers.py` (file I/O)

Ports `readers.py` near-verbatim. **One import change:** replace
`from helao.helpers.hlo_data import read_hlo_bytes` with the framework loader
`from helao.framework.adapters.loaders.hlo_loader import read_hlo_bytes` (SP6;
same `(content: bytes) -> (meta, data)` contract). Public surface preserved:
`read_dataset(locator, fmt=None)`, `make_zip_locator(zip_path, member)`,
`parse_locator(locator)`, `ZIP_PREFIX`, `ZIP_SEP`.

### 4.3 `helao/framework/adapters/data_browser/sources.py` (filesystem/zip I/O)

Ports `sources.py` near-verbatim. **One import change:** `make_zip_locator` from
the sibling framework `readers`. Public surface preserved: `INDEX_COLUMNS`,
`SOURCES`, `GROUPS`, `RunsSourceIndex`, `DerivedSourceIndex`, `SourceIndex`,
`build_source_index(root, source)`, `get_index(root, source, date_start, date_end)`,
and the module-level helpers the tests exercise (`_list_day_dirs`, `_in_range`).

### 4.4 `helao/framework/adapters/data_browser/loader.py` (I/O)

New home for `state.load_selected`:

`load_selected(index_df, positions) -> (datasets: list[SelectedDataset], skipped: list[tuple[str, str]])`

Reads chosen index rows via the sibling `readers.read_dataset`, builds
`domain.data_browser.SelectedDataset` objects, and returns `(datasets, skipped)`
with the same skip semantics (unavailable rows and unreadable files skipped;
logging is the caller's job). Imports `readers` (I/O) and the domain dataclass —
an adapter building a domain object, which the boundary contract permits.

> This split is the only behavioral re-organization: it moves the sole I/O
> function out of the (otherwise pure) `state.py` so the domain module is clean.
> Function signature and semantics are unchanged.

### 4.5 `helao/framework/app/data_browser.py` (Bokeh)

Ports `app.py` (`build_document(vis)` + `_UI`). Import changes only:
- `sources` ← `helao.framework.adapters.data_browser.sources`
- pure transforms (`available_columns`/`build_trace`/`downsample`/`summary_row`/
  `SUMMARY_COLS`) ← `helao.framework.domain.data_browser`
- `load_selected` ← `helao.framework.adapters.data_browser.loader`

`build_document(vis)` keeps its signature and consumes the same `Vis` surface
(`vis.helaodirs.root`, `vis.server_cfg`, `vis.print_message`) that SP-VIS-1's
`app/vis.py` provides. Widget wiring, callbacks, and layout unchanged.

### 4.6 `helao/framework/adapters/data_browser/__init__.py`

Package marker (the legacy `__init__.py` is 2 lines; keep equivalent).

## 5. Data flow

```
makeBokehApp (deployment, later) → build_document(vis)        [app/data_browser]
  ├─ Scan  → sources.get_index(root, source, start, end)      [adapters/.../sources]
  │            → DataFrame(INDEX_COLUMNS)
  ├─ Add   → loader.load_selected(df, picks)                  [adapters/.../loader]
  │            → readers.read_dataset(locator, fmt)            [adapters/.../readers → hlo_loader]
  │            → [domain.SelectedDataset]
  └─ Plot/Table → domain.build_trace/downsample/summary_row   [domain/data_browser]
```

## 6. Error handling (parity)

- `readers.read_dataset` raises `ValueError` on unsupported format (unchanged).
- `loader.load_selected` skips unavailable rows (`not available`/empty `locator`)
  and catches read exceptions per-row into `skipped` (unchanged).
- `sources` `_safe_yaml`/`_safe_yaml_bytes` swallow parse errors → `{}`; bad zips
  skipped (unchanged).
- `build_document` `_do_scan` catches scan exceptions, sets the status Div, and
  logs via `vis.print_message(..., error=True)` (unchanged).

## 7. Test strategy

Port the existing 22-test standalone suite
(`helao/deploy/test/tests/test_data_browser.py`) to pytest under
`helao/framework/tests/`, repointed at the framework modules. Split by layer to
mirror the new structure:

- `test_domain_data_browser.py` — `available_columns`, `build_trace` (+ missing
  column → None), `downsample`, `summary_row`, `SelectedDataset.columns`.
- `test_adapters_data_browser_readers.py` — hlo file, json columnar, json records,
  parquet, hlo-from-zip, unsupported-format `ValueError`, `make_zip_locator`/
  `parse_locator` round-trip.
- `test_adapters_data_browser_sources.py` — `_list_day_dirs`/`_in_range`,
  RUNS_FINISHED tree index, RUNS_SYNCED zip index, PROCESSES resolve-to-runs +
  missing-file-unavailable, ANALYSES local + s3-only-unavailable, `get_index`
  dispatch (incl. empty-source columns).
- `test_adapters_data_browser_loader.py` — `load_selected` end-to-end (available
  row loads; unavailable/empty index skipped).
- `test_app_data_browser.py` — `build_document` smoke (roots added against a fake
  `Vis` + real Bokeh `Document`), plot-tab builds traces, table-tab summary+rows,
  replot-and-clear-safe (stale summary index must not raise).

Reuse the legacy test's fixtures (`_write_hlo`, `_make_finished_tree`,
`_make_synced_zip`, `_make_process`, `_make_analysis`, `_FakeVis`/`_FakeDirs`).
**Drop** `test_shims_expose_makebokehapp` (it asserts the legacy deploy shims,
which SP-VIS-2 does not touch). Tests run under the `helao` conda env (3.12).

The AST boundary check must stay green; add no domain→I/O import.

## 8. API parity

Public names preserved within each module (so a later deployment cut-over is an
import-path change): `read_dataset`, `make_zip_locator`, `get_index`, `GROUPS`,
`SOURCES`, `INDEX_COLUMNS`, `RunsSourceIndex`, `DerivedSourceIndex`,
`SelectedDataset`, `available_columns`, `build_trace`, `downsample`,
`summary_row`, `SUMMARY_COLS`, `load_selected`, `build_document`, `_UI`.

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Behavior drift from the load_selected move | Signature + semantics unchanged; ported end-to-end test covers it |
| Framework hlo loader differs from legacy `read_hlo_bytes` | Both return `(meta, data)`; ported reader tests assert the hlo/zip data values |
| Re-layer introduces a domain→I/O import | Boundary AST test fails the build; load_selected lives in adapters |
| Scope creep into deploy rewiring / operator | Hard non-goals (§2) |

## 10. Done criteria

- `domain/data_browser.py`, `adapters/data_browser/{__init__,readers,sources,loader}.py`,
  `app/data_browser.py` exist with parity APIs.
- Ported pytest suite passes under `helao` env; full framework suite still green;
  AST boundary check still green.
- No legacy `core/**` or `deploy/**` file modified (pure addition).
- Spec committed; foundation ready for SP-VIS-3 (operator).
