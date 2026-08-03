# Reflex data browser — design

**Status:** design, not yet implemented.
**Branch:** `feat/reflex-data-browser`.
**Parent spec:** `docs/superpowers/specs/2026-08-01-reflex-ui-design.md`, which built the
Reflex/xy foundation and left `/browser` as a stub route. Every decision there
still binds — above all Decision 1, coexistence: the Bokeh data browser is not
removed, deprecated, or modified.

**Why this one first.** The operator is the bigger prize (3077 lines), but the
data browser is the better first port: it exercises the same shapes the
operator needs — a large filterable table, multi-row selection driving a plot,
tabbed detail views, blocking I/O behind a responsive UI — at a fifth the size,
and against a logic layer that is already backend-agnostic. Patterns invented
here are the ones the operator inherits.

## What is actually being ported

`helao/core/servers/data_browser/` is already well split, and only one of its
four modules is Bokeh-aware:

| Module | Lines | Bokeh? | Fate |
|---|---:|---|---|
| `readers.py` | 96 | no | reused verbatim |
| `state.py` | 131 | no | reused verbatim |
| `sources.py` | 386 | no | reused verbatim |
| `app.py` | 329 | **yes** | gets a Reflex twin beside it |

So the port is ~329 lines of UI, not 945. **No file in the reused set may be
edited to suit Reflex.** If the Reflex UI wants something they do not expose,
that is a signal the logic belongs in the shared layer — add it there and let
the Bokeh app keep working — not a licence to fork behaviour.

`state.py` is the contract: `available_columns`, `build_trace`, `downsample`,
`summary_row`, `load_selected`, and the `SelectedDataset` dataclass. The Reflex
UI is a different rendering of exactly those.

## The existing UI, as the port target

From `app.py`, the surface to reproduce:

- **Source controls** — a group radio (`sources.GROUPS`), a source `Select`,
  `From`/`To` date text inputs (`YY.WW/MMDD`), and a **Scan** button.
- **Index** — a `Filter index` text input over a `DataTable` of scan results,
  with multi-row selection.
- **Actions** — `Add to plot` and `Clear plot`.
- **Detail tabs** — a plot tab (X / Y / trace-type selects over one figure) and
  a data tab (summary table and a rows table).

Nothing is dropped. Two things change shape, both deliberately:

- `parse_bokeh_input` has no role: Reflex delivers typed Python from its inputs.
- The date inputs stay free text rather than becoming date pickers, because the
  `YY.WW/MMDD` run-tree format is not a calendar date and a picker would have to
  invent a mapping. Validation belongs in the shared layer if it is wanted.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | Reuse `sources`/`state`/`readers` untouched; add `app_reflex.py` beside `app.py` | The split already exists and is the reason this port is small. Two UIs over one logic layer is the coexistence Decision 1 requires. |
| 2 | One plain `rx.State` subclass for the page, **not** a mixin | The panel states are mixins because `make_panel_state` mints one class per server and Reflex vars on a concrete ancestor are shared. The browser is a single page with a single state — the mixin machinery would be cargo cult. |
| 3 | Scanning and file reads run in `@rx.event(background=True)` | `sources.get_index` walks the run tree and `load_selected` opens files; on a station's `RUNS_*` tree both are slow enough to freeze a synchronous handler. The Bokeh app blocks its document; Reflex must not repeat that. |
| 4 | Add one facade function, `plots.traces`, for independently-x'd traces | Every existing facade entry (`time_series`, `spectra`) assumes one shared x. Selected datasets each carry their own x column. This is a real gap, not a workaround. |
| 5 | Filtering and selection are server-side over the index DataFrame | The index can run to thousands of rows. Shipping it all into Reflex state to filter in the browser would push exactly the bulk data Decision 8 of the parent spec keeps out of the state channel. |
| 6 | Buffer-store key is `browser-{session_token}` | Same session-scoping rule the panels learned the hard way: the store holds one frame per key while the version counter is per-session state, so a shared key would 404 two tabs into frozen charts. |
| 7 | Trace type maps onto xy marks via an argument, not onto separate facade calls | `plots.traces` takes the mark kind. Near-identical facade functions per kind would be the step-line workaround all over again. The kinds are exactly the Bokeh original's `line` and `scatter`; xy also ships `step`, but adding it here would make this a feature, not a re-rendering. |

## Architecture

```
helao/core/servers/data_browser/
  readers.py      (unchanged)
  state.py        (unchanged)   <-- the contract
  sources.py      (unchanged)
  app.py          (unchanged)   <-- Bokeh, still live
  app_reflex.py   (new)         <-- Reflex page, built from state.py
```

The Reflex page is registered on the existing app's `/browser` route, replacing
the stub. `helao/core/servers/reflex/app.py` gains no browser-specific
knowledge beyond importing the page builder — the same shape `_render_panel`
already uses for panels.

**State layout** (one class, per session):

- `group`, `source`, `date_start`, `date_end` — the scan controls.
- `index_rows`, `index_filter`, `selected_positions` — the index table and its
  selection, held as integer positions into the scanned DataFrame, which is what
  `state.load_selected` already takes.
- `xcol`, `ycol`, `trace_kind` — plot controls, options from
  `state.available_columns`.
- `chart_spec`, `chart_url`, `chart_layout`, `version` — the three vars
  `plots.chart` binds plus its monotonic token, exactly as the panels do.
- `summary_rows`, `rows_preview` — the data tab.
- `scanning`, `loading`, `error` — so a slow scan is visible rather than looking
  like a hang, and a skipped file says why.

The scanned DataFrame itself lives in a process-side cache keyed by session, not
in a Reflex var: it is bulk data, and Decision 8 of the parent spec keeps bulk
data off the state channel.

## Error handling

`state.load_selected` already returns `(datasets, skipped)` with a reason per
skipped file, and the Bokeh app logs them. The Reflex page **surfaces** them:
a file that is not available locally or fails to parse is the single most
common thing a user hits, and a silent omission from the plot is the worst
possible presentation. A scan that finds nothing says so rather than rendering
an empty table with no explanation.

## Testing

The reused layer already has tests (`helao/deploy/test/tests/test_data_browser.py`).
This port adds:

- **Page state, headless.** The scan/filter/select/plot transitions driven
  against a temporary run tree, asserting the state vars — no browser needed.
- **`plots.traces`.** Shape validation, independent x per trace, empty and
  all-non-finite inputs, mark-kind selection.
- **Route registration.** `/browser` resolves to the real page, not the stub —
  the parent spec's route test currently asserts the stub, so it changes here.
- **A live browser check.** The lesson from the parent port is unambiguous: six
  rendering defects survived a green unit suite because nothing loaded a page.
  Playwright and chromium are installed; a headless check that scans, selects,
  plots, and asserts a painted canvas is part of this work, not a manual step.

## Out of scope

- The operator. Separate spec, full-fidelity, immediately after this.
- Any change to the Bokeh data browser.
- New data sources or readers. This is a re-rendering, not a feature.
