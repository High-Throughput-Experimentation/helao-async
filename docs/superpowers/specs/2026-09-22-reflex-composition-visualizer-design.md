# Reflex composition visualizer — design

**Date:** 2026-09-22
**Status:** approved, ready for an implementation plan
**Scope:** the Reflex UI stack only. The Bokeh stack is untouched and gains nothing.

## 1. What this is

A new page at `/composition` that answers one question: *what did XRF measure
across this plate, and where?* An operator types a plate id, presses Retrieve,
and the page loads every XRF process recorded for that plate from the HELAO
metadata API. Two dropdowns group the retrieved processes (by `run_use` and by
sequence), two more select what to plot (a fluorescence transition and a unit),
and a Plot button renders the selection two ways: a spatial scatter over the
plate's platemap coordinates, and a ternary diagram with a transition at each
vertex. Clicking a point loads that sample's source spectrum and its full
analysis output.

The page binds to no HELAO server. It is not a live visualizer: nothing ticks,
nothing subscribes to a WebSocket, and it renders identically whether or not an
orchestration group is running. In that respect it is the data browser's
sibling, not the live visualizers'.

## 2. Verified data path

Every fact below was confirmed against the production metadata API
(`https://helao-api.caltech-hte.modelyst.com/api`) on 2026-09-22 using plate
10244. The whole path is unauthenticated HTTP; **only the platemap coordinates
need credentials**, and only for the scatter plot.

### 2.1 Processes for a plate

```
POST /api/search
{
  "size": 500, "page": 1, "match_keys": true,
  "filters": [
    {"field": "process_params.plate_id", "operation": "eq", "value": 10244},
    {"field": "entity_type", "operation": "in", "value": ["PROCESS"]}
  ]
}
```

Returns 497 items for plate 10244. `process_params.plate_id` is the filter that
selects a whole plate. The `process_params.source_csv_label` filter in the
original request (`legacy__solid__10244_42`) selects **one sample**, not a
plate, and `Operation` offers no `like` — the enum is exactly
`gte`, `lte`, `eq`, `match`, `contains`, `in` — so a prefix match over labels
would be a `contains` heuristic. Filtering on the numeric `plate_id` is exact
and needs no string convention.

Each item carries `process_uuid`, `process_timestamp`, `process_name`,
`run_use`, `sequence_uuid`, `experiment_uuid`, `campaign_name`, the full
`process_params` dict (including `plate_id`, `source_csv_label`, `stage_label`,
`stage_x`/`stage_y`), and a `files` list. The files list is where the two
artifacts the page needs are named, each with its own `action_uuid`:

| `file_type` | contents |
|---|---|
| `xrfspec_helao__json_file` | the spectrum: `channel`, `ev`, `intensity`, 4000 points |
| `xrfs_quant_helao__json_file` | the analysis output: per-transition values |
| `xrfcount_helao__json_file` | raw counts, not used by this page |
| `edax_orbis_spc__file` | the vendor SPC, not used by this page |

A PROCESS record carries **no** `sequence_timestamp`, `sequence_name`,
`sequence_label`, `experiment_name` or `samples_in`; those keys are present and
`null`. This is why grouping by sequence needs a second request.

### 2.2 Sequence timestamps

```
POST /api/search
{
  "size": 500, "page": 1, "match_keys": true,
  "filters": [
    {"field": "sequence_uuid", "operation": "in", "value": [...]},
    {"field": "entity_type", "operation": "in", "value": ["SEQUENCE"]}
  ]
}
```

Returns `sequence_timestamp`, `sequence_name` and `sequence_label` per
sequence. Plate 10244's 497 processes span exactly two sequences
(`2026-08-13T11:54:21` and `2026-09-10T17:02:37`, both named
`XRFS_noStandards`, both labelled `CoYPt-102441`) and two `run_use` values
(`post_anneal` 398, `pre_anneal` 99). Two sequences with the same name and the
same label, two months apart, is precisely why the sequence dropdown must show
the timestamp rather than the name.

### 2.3 Analysis output per process

```
POST /api/file/raw-data
{"key": "raw_data/<action_uuid>/<file_name>"}
```

Returns the HLO decoded as `{"data": {"meta": {...}, "data": {...columns...}}}`.
For `xrfs_nostds-0.0.0.0__2.hlo.json` the columns are:

```
element             ["Co", "Y",   "Y",   "Pt",  "Pt"]
transition          ["Co.K","Y.K","Y.L","Pt.L","Pt.M"]
net_counts, net_cps, net_cps_alpha,
nanomoles, nanomoles_1se, nanomoles_per_cm2      (one value per transition)
atomic_fraction     [0.167, 0.814, null, 0.019, null]
global_sample_label, analysis_name, output_type, calibration_date
```

The S3 key is **derived**, not looked up: `POST /api/file/metadata
{"file_name", "action_uuid"}` returns exactly
`raw_data/<action_uuid>/<file_name>`, and posting that derived key to
`/api/file/raw-data` was verified to return the same payload. Deriving it
halves the request count for a plate load, from two calls per process to one.
The metadata call stays as the fallback for a key that 404s, so a record stored
under a different convention still resolves.

`atomic_fraction` is populated on exactly one transition per element — the
calibrated one. The other transitions carry every other unit but `null` here.
This is not a defect; it is what "calibrated" means in this pipeline.

`POST /api/compositions-by-samples` returns `[]` for these samples, so the
composition endpoints are not a shortcut here.

### 2.4 Spectrum on click

```
POST /api/file/plottable-data
{"file_name": "...__1.hlo.json", "file_type": "xrfspec_helao__json_file",
 "action_name": "run_XRF", "action_uuid": "..."}
```

Returns `plot_type: "line"` and `data.series` with `channel`, `ev` and
`intensity`, 4000 points each. `action_name` is not on the PROCESS record; it
comes from `GET /api/action/{action_uuid}` (verified: `run_XRF`). One action
lookup per clicked point, not per plate.

### 2.5 Platemap coordinates

The metadata API exposes no `x`/`y`. `POST /api/plate/{plate_id}/samples`
returns `global_label`, `sample_no`, `plate_id` and timestamps, but no
position, and `GET /api/plate/10244` 404s. Coordinates come from
`helao.helpers.plate_api.HTEPlateAPI.get_platemap_plateid(plate_id)`, which
reads the platemap text file from S3 and therefore needs `HELAO_CREDENTIALS`.

`process_params` does carry `stage_x`/`stage_y` (e.g. 44.451 / 3.934), but
those are ORBIS stage coordinates in a different frame and orientation from the
platemap. They are **not** used as a fallback: two coordinate frames rendered
into the same axes, distinguished only by a badge, is a worse failure than an
absent plot.

The plate API is **opt-in per station**: `plate_api_for` in
`helao/ui/reflex/operator.py` builds an `HTEPlateAPI` only when a server's
config declares `params.plate_api: HTEPlateAPI`, and returns `None` otherwise
with a log line. An unrecognised value is ignored rather than imported, so a
typo cannot pull in something arbitrary. This page keeps that property but
cannot use that function unchanged, because it has no server of its own — see
§3.0.

### 2.6 The operator already solved half of this

`helao/ui/reflex/operator.py` carries a plate-map panel with the same shape:
a plate id field, `HTEPlateAPI.get_platemap_plateid`, a `plots.scatter_map`
render, and click-to-select. Five module functions there are directly reusable
and are the reason this design writes less new code than it first appears:

| function | what it does |
|---|---|
| `plate_api_for(server_cfg)` | opt-in `HTEPlateAPI` construction, cached |
| `platemap_points(pmdata)` | platemap rows → `(xs, ys, sample_nos)`, non-numeric rows dropped whole |
| `nearest_sample(pmdata, x, y)` | nearest plotted sample to a click |
| `composition_text(entry)` | the platemap's own A–H fractions as one line |
| `sample_summary(pmdata, sample_no)` | code + composition for one sample |

Two facts about them matter to this design and are easy to get wrong:

- **`on_select` delivers a coordinate, not a row id.** `OperatorPlateState.on_select`
  reads `payload["x"]` and `payload["y"]` and resolves the point by nearest
  neighbour. There is no id in the payload, and `xy_component.py` wires only
  `on_select` — no `onClick`, no `onHover`. Any design that assumed a row index
  would come back from the chart is wrong.
- **`platemap_points` numbers samples positionally** (`index + 1`), not from the
  platemap's own `sample_no` column, which `HTEPlateAPI.get_platemapdlist`
  populates from `map_df.Sample`. For the operator the two agree closely enough
  that nothing surfaced. This page joins API records — whose sample number comes
  from `source_csv_label` — against platemap rows, so it **must** join on the
  `sample_no` field and never on the positional index. See §3.0.

### 2.7 A defect found in `OpenAPIClient`

`helao/helpers/openapi_client.py` derives each bound method's name from the
operation's `summary` and **silently overwrites a collision**. The spec declares
both `POST /api/file/metadata` ("Read Metadata", body `file_name` +
`action_uuid`) and `GET /api/output-file/metadata` ("Read Metadata", query
`file_path`); only one `read_metadata` is bound, and it is the
`output-file` one. `presign_url` collides the same way. So the client cannot
reach `POST /api/file/metadata` at all, and a caller who asks for it gets a
`ValueError` about a missing `file_path` rather than a wrong-endpoint error.

This design works around it (see §3.1) rather than fixing it: repairing the
name derivation changes the method names other callers already bind to, which
is a separate change with its own blast radius. The workaround is one `httpx`
call on a fallback path. **The workaround must carry a comment naming this
cause**, or the next reader will "simplify" it back into the client.

## 3. Architecture

Three layers, matching how the data browser and the operator are already split.

```
helao/ui/shared/platemap.py       hoisted from operator.py, consumed by both
helao/ui/shared/composition/      backend-agnostic, no reflex import
    api.py          metadata-API calls
    model.py        CompositionRecord
    grouping.py     group keys and labels
    ternary.py      barycentric -> cartesian
    interp.py       RBF over the platemap

helao/ui/reflex/composition.py    the /composition page
helao/ui/reflex/operator.py       - the five hoisted functions, + re-export
helao/ui/reflex/plots.py          + ternary(), the only xy importer
helao/ui/reflex/app.py            + the route, + configure_composition
helao/ui/shared/palette.py        + the page tint
```

The shared layer exists even though only Reflex consumes it today. The reason
is not a future Bokeh port — it is that `api.py`, `ternary.py` and `interp.py`
are the parts worth testing, and a module that imports `reflex` cannot be
tested without a Reflex app. This mirrors `helao/ui/shared/data_browser/`,
where `readers.py`/`state.py`/`sources.py` are shared and each stack owns only
its document.

### 3.0 `shared/platemap.py` — hoisted, not re-implemented

The five functions in §2.6 move out of `helao/ui/reflex/operator.py` into a new
`helao/ui/shared/platemap.py`, together with `FRACTION_KEYS`, `PLATE_APIS`,
`_PLATE_API_CACHE` and `_as_number`. `operator.py` imports them back under
their existing names, so every one of its call sites, and every test that
reaches them through `helao.ui.reflex.operator`, keeps working untouched.
`test_standalone_operator.py`'s 59 tests and `test_reflex_operator.py` are the
gate on that: they must pass with no edits.

Re-implementing these in the composition page instead would be the most common
form of slop in this repo — a second nearest-neighbour search, a second
coordinate coercion, and a second place where a non-numeric platemap row takes
down a chart. Hoisting is the smaller diff *and* the one that keeps the two
pages agreeing about what a plate looks like.

Two additions the hoist carries:

```python
def plate_api_for_config(world_cfg: dict):
    """The first plate API any server in this config declares, or None."""

def platemap_rows(pmdata) -> list[dict]:
    """Plottable platemap rows, each keyed by its own ``sample_no``."""
```

`plate_api_for_config` exists because `/composition` binds to no server, so
there is no single `server_cfg` to read `params.plate_api` from. It scans
`world_cfg["servers"]` and returns the first configured plate API, preserving
the opt-in property: a config that declares none still yields `None`.

`platemap_rows` exists because `platemap_points` numbers samples positionally
(§2.6) and this page must join on the platemap's own `sample_no`. It returns
the same rows `platemap_points` keeps — coordinates coerced, unconvertible rows
dropped — but carries `sample_no` from the row rather than from its index.
`platemap_points` is left exactly as it is; changing its numbering would change
the operator's behaviour, which is out of scope here.

### 3.1 `shared/composition/api.py`

Four functions, all `async`, all taking an explicit client so tests can pass a
stub:

- `search_processes(client, plate_id) -> list[dict]` — pages `POST /api/search`
  until `len(items) >= total`, at `size=500`. Plate 10244 needs one page; a
  larger plate must not silently truncate.
- `fetch_sequences(client, sequence_uuids) -> dict[str, dict]` — one
  `POST /api/search` over SEQUENCE, keyed by `sequence_uuid`.
- `fetch_quant(client, action_uuid, file_name) -> dict` — derived key first,
  `POST /api/file/metadata` on 404.
- `fetch_spectrum(client, action_uuid, action_name, file_name) -> dict` —
  `POST /api/file/plottable-data`.

`AsyncOpenAPIClient` from `helao.helpers.openapi_client` provides `search`,
`read_plottable_data`, `read_raw_data` and `read_action` (verified bound). The
single `httpx` call is the `/api/file/metadata` fallback, for the reason in
§2.7.

The API base URL is a module constant here. The only existing `API_SPEC_URL`
lives in a private deployment's batch-processing scripts; this page must not
import a private deployment, so the constant is restated. That is a deliberate
duplication of one string, not an extracted shared module: hoisting it would
make the parent repo's UI depend on a deployment's notion of which API is
canonical.

### 3.2 `shared/composition/model.py`

```python
@dataclass(frozen=True)
class CompositionRecord:
    plate_id: int
    sample_no: int
    global_label: str
    run_use: str
    sequence_uuid: str
    sequence_timestamp: str      # "" when the sequence search returned nothing
    process_uuid: str
    process_timestamp: str
    quant_action_uuid: str
    quant_file_name: str
    spectrum_action_uuid: str
    spectrum_file_name: str
    values: dict[str, dict[str, float | None]]   # transition -> unit -> value
```

`sample_no` is parsed from `process_params.source_csv_label`
(`legacy__solid__10244_42` → 42), with `process_params.stage_label` as the
fallback. A record whose sample number cannot be determined is dropped with a
log line rather than plotted at an invented position.

### 3.3 `shared/composition/grouping.py`

Two group functions returning `dict[label, list[CompositionRecord]]`:

- by `run_use` — label is the value itself (`pre_anneal`, `post_anneal`), and
  `""` becomes `"(no run_use)"`.
- by `sequence_uuid` — label is
  `f"{sequence_timestamp} · {sequence_uuid[:8]}"`, falling back to the bare
  uuid when the timestamp is unknown. Sorted newest first.

Both dropdowns carry an "All" entry, and they compose: selecting a `run_use`
*and* a sequence intersects.

### 3.4 `shared/composition/ternary.py`

```python
def barycentric_to_cartesian(a, b, c) -> tuple[np.ndarray, np.ndarray]
def triangle_edges() -> tuple[np.ndarray, np.ndarray]
def vertex_positions() -> tuple[np.ndarray, np.ndarray]
```

The three component arrays are normalised to sum to 1 per point before the
transform; a point whose three values sum to zero is dropped. Vertices are the
unit triangle with apex at the top: `(0,0)`, `(1,0)`, `(0.5, √3/2)`.

### 3.5 `shared/composition/interp.py`

```python
def rbf_surface(xs, ys, values, target_xs, target_ys, *, kernel="thin_plate_spline")
    -> np.ndarray
```

`scipy.interpolate.RBFInterpolator` (scipy 1.18.0 present in the `helao` env),
fit on the measured points and evaluated at **every** platemap position, which
is what makes the toggle show more points than were retrieved. Guards: fewer
than four measured points returns an empty array and the toggle reports "not
enough measured points"; duplicated coordinates are collapsed to their mean,
because `RBFInterpolator` raises on a singular matrix rather than degrading.

### 3.6 `reflex/plots.py` — one new function

```python
def ternary(a, b, c, *, labels, values=None, panel_id="ternary", version=0)
    -> ChartPayload
```

xy 0.0.5 has no ternary mark; its `EXPORTS` list contains no such name, and
`polar_chart`/`radar_chart` are a different projection. The implementation is
`xy.scatter` over the transformed coordinates, three `xy.line` marks for the
edges, and three `xy.text` marks for the vertex labels, assembled by the
existing `_chart` and published by the existing `_publish`. Axes are rendered
with empty labels: a ternary diagram has no meaningful x or y axis, and the
vertex labels carry the identification instead.

The plate scatter and the RBF surface both reuse `scatter_map`, which already
takes a per-point `values` array for colour and already drops non-finite
points across all three arrays. The spectrum reuses `spectra`.

`plots.py` stays the only module importing `xy`; the existing isolation test
must still pass.

### 3.7 `reflex/composition.py` — the page

One `rx.State` subclass, `CompositionState`, owning: the plate id field, the
retrieved records, the four dropdown selections, the RBF toggle, the selected
sample, and the three chart payload triples (spec / buffer url / layout) that
`plots.chart` binds.

Three rules the Reflex stack has already paid for, restated because each one
fails at a different time:

- **`plots.chart(...)` is called once, in the page body.** The facade functions
  (`scatter_map`, `ternary`, `spectra`) are called in event handlers and their
  `ChartPayload` assigned into state. A facade call in the body paints once and
  never updates.
- **No `while True`, no `background=True` polling loop.** This page has no
  cadence at all: every render is caused by a button press or a point click.
  There is nothing to tick.
- **Every `rx.foreach` var is annotated with its element type**
  (`list[list[str]]`, not `list`). A bare `list` fails the frontend build with
  `ForeachVarError`, which surfaces only at `reflex export`.

The page is built **before** `add_page`, not inside its callable, so the state
class and its event handlers exist in a `--backend-only` process.

The world config reaches the page through a `configure(world_cfg, server_key)`
module function called from `build_app`, exactly as `configure_operator` and
`configure_control` already are. That is where `plate_api_for_config` finds its
config. Resolving a config path relative to the cwd is a bug here — the Reflex
process runs from `_app/`, not the repo root — but this page reads no
config-relative paths, so it needs no equivalent of the operator's
`rooted_config`.

## 4. Interaction

```
[ plate id ____ ] (Retrieve)        <- one text field, one button

run_use:  [ All      v ]   sequence: [ 2026-09-10T17:02:37 · 07528a44  v ]
transition: [ Co.K   v ]   unit:     [ atomic_fraction               v ]
                                                          (Plot)

+-- plate map --------------+  +-- ternary ------------------+
|  x,y scatter, coloured    |  |   three transition vertices |
|  by the selected unit     |  |                             |
|  [ ] RBF interpolate      |  |                             |
+---------------------------+  +-----------------------------+

+-- selected sample --------------------------------------------+
| legacy__solid__10244_42   sample 42   post_anneal              |
| transition  net_counts  net_cps  nanomoles  atomic_fraction ...|
| Co.K        271.2       1550.9   16.41      0.1674             |
| ...                                                            |
+----------------------------------------------------------------+
+-- spectrum ------------------------------------------------------+
|  intensity vs ev                                                 |
+------------------------------------------------------------------+
```

**Retrieve** runs the two searches, then fans out the quant fetches, then
populates the transition and unit dropdowns from the union of what actually
came back — not from a hardcoded element list, because the transitions differ
per plate.

**The transition dropdown lists transitions literally** — `Co.K`, `Y.K`,
`Y.L`, `Pt.L`, `Pt.M` — not elements. The data is per-transition; collapsing to
elements requires a selection rule (the one non-null `atomic_fraction`), and a
rule that silently drops a sample whose transitions are all uncalibrated is
worse than a dropdown where `Y` appears twice. The ternary tab presents three
such selectors, one per vertex, defaulting to the first three distinct
elements' calibrated transitions.

**Unit dropdown:** `net_counts`, `net_cps`, `net_cps_alpha`, `nanomoles`,
`nanomoles_1se`, `nanomoles_per_cm2`, `atomic_fraction` — read from the quant
payload's columns, minus the non-numeric ones (`element`, `transition`,
`global_sample_label`, `analysis_name`, `output_type`, `calibration_date`).
Handing a string column to `plots` raises `could not convert string to float`
from inside the render and takes down the whole chart, so the filter is not
cosmetic.

**Clicking a point** fills the selected-sample panel with every transition ×
every unit for that sample, and loads the spectrum into the third chart
(`intensity` on y, `ev` on x). There is no hover tooltip: xy's
`tooltip(fields=...)` reads fields off a mark's data columns, and whether
arbitrary extra per-point columns survive `build_payload_split` into the
browser is unverified. The details panel is the guaranteed surface and needs no
xy capability the stack does not already use.

**Point selection arrives as a coordinate, not an index.** `plots.chart`'s
`on_select` handler receives `{"x": ..., "y": ...}` and nothing else (§2.6), so
the clicked record is resolved by `shared.platemap.nearest_sample` on the plate
map, and by a nearest-neighbour search over the transformed ternary coordinates
on the ternary diagram. The ternary search happens in the transformed plane,
because that is the plane the click is in; searching the barycentric triples
would find a different point wherever the triangle is anisotropic on screen.

On the RBF surface a click may land on an interpolated position with no
measurement behind it. Those points resolve to the nearest **measured** sample,
and the details panel says which sample it snapped to, so an interpolated value
is never displayed as if it had been measured.

**The RBF toggle** switches the plate scatter between the measured points and a
surface evaluated at every platemap position. It is disabled, with a note,
whenever the platemap is unavailable — the toggle needs the full position list,
not just the measured ones.

**When no plate API is configured, or `HTEPlateAPI.has_access` is false, or
`get_platemap_plateid` raises**, the plate-map tab renders a note distinguishing
the three — no plate API declared in this config, credentials unavailable, or
this plate's map could not be read — because the operator action differs in each
case. The ternary diagram, the details panel and the spectrum are unaffected:
none of them needs a coordinate.

## 5. Cost and concurrency

A plate load is one search, one sequence search, and one `raw-data` call per
process — 499 requests for plate 10244. Three things bound it:

- A `asyncio.Semaphore(30)` over the quant fan-out, matching the bound
  `get_xrfs_list` already uses against this API.
- An in-process cache keyed by `action_uuid`, so re-grouping, re-selecting a
  unit, or re-plotting costs nothing. Retrieve on the same plate id re-uses it;
  a different plate id does not evict it.
- `return_exceptions=True` on the gather, with failures counted and reported in
  a status line rather than aborting the load. One unreadable HLO out of 497
  must not cost the other 496.

A progress count (`n / total`) is written into state as the fan-out completes,
so a 499-request load is not a frozen page.

## 6. Route registration and the palette

`SHELL_ROUTES` in `helao/ui/reflex/app.py` gains `"/composition"`, `_nav()`
gains a `Composition` link, and `build_app` gains an `add_page` for it,
alongside `/browser`. Like every other route it is registered unconditionally;
`params.pages` does not decide which pages exist.

`REFLEX_PAGE_TINTS` gains `"/composition": "lime-50"`, and `TW` gains
`"lime-50": "#f7fee7"`.

`lime-50` was chosen by measurement against the four unused 50-level candidates:

| candidate | slate-900 | slate-600 | slate-500 | min ΔE to existing tints | borders whose worst tint moves |
|---|---|---|---|---|---|
| `lime-50` | 17.25 | 7.32 | 4.60 | 5.30 (`amber-50`) | none |
| `teal-50` | 17.12 | 7.27 | 4.56 | 2.97 (`emerald-50`) | none |
| `cyan-50` | 17.16 | 7.28 | 4.57 | 4.17 (`sky-50`) | none |
| `indigo-50` | 15.97 | 6.78 | 4.26 | 2.25 (`violet-50`) | all five |

`lime-50` is the only candidate that is both further from its nearest existing
tint than the existing tints are from each other (their minimum pairwise ΔE is
3.21) and leaves every table border's weakest surface unchanged. `indigo-50`
fails on both counts and would additionally add a fourth tint on which
`slate-500` is under the body floor.

Test obligations in `helao/core/tests/test_palette.py`, all with **measured**
values:

- `PAGE_TINT_TEXT_ROWS` gains `("slate-900", "lime-50") = 17.25` and
  `("slate-600", "lime-50") = 7.32`. `test_page_tint_rows_cover_every_route_twice`
  then passes unchanged.
- `SLATE_500_ON_TINT_ROWS` gains `("slate-500", "lime-50") = 4.60`.
- `test_slate_500_fails_the_body_floor_on_three_of_the_six_tints` is **renamed**
  to `..._of_the_seven_tints`; its asserted set stays
  `{"sky-50", "violet-50", "rose-50"}`, because `lime-50` at 4.60 clears the
  4.5 floor. Its docstring's "a sixth route" sentence gains the seventh.
- `test_slate_600_clears_every_tint_by_a_real_margin` passes unchanged
  (7.32 ≥ 6.5).
- `test_border_rows_cover_every_hue_at_its_worst_tint` passes unchanged: no
  border is weaker on `lime-50` than on its current worst tint.
- `test_reflex_page_tints_cover_the_shell_routes` passes once both the route and
  the tint are added; it asserts set equality with `SHELL_ROUTES` *and* that the
  tints are all distinct, so adding one without the other fails.

The AST colour sweep (`test_palette.py`) is unaffected as long as
`composition.py` carries no literal colour and reaches its hues through
`reflex_page_class`, `reflex_header_class` and `reflex_table_class`. The new
sweeper-exempt-path list stays at exactly two entries.

The Reflex bundle rebuilds itself: the stamp includes a content hash of every
`helao/` module the app imported, so the new page and the edited palette both
invalidate it at the next launch. No manual `build_reflex_bundle.py` step is
required where `node_modules` is warm.

## 7. Testing

Pure-logic tests, no Reflex app and no network:

- `ternary.py`: a known barycentric triple maps to its known cartesian point;
  normalisation of an unnormalised triple; a zero-sum point is dropped;
  vertices and edges close the triangle.
- `interp.py`: an RBF fit on a known plane reproduces that plane at unmeasured
  positions; fewer than four points returns empty; duplicated coordinates do
  not raise.
- `grouping.py`: sequence labels carry the timestamp; two sequences sharing a
  name and label produce two distinct labels; an unknown timestamp falls back
  to the bare uuid; "All" composes with the other dropdown.
- `model.py`: `sample_no` parsed from `source_csv_label`, from `stage_label`
  when the label is absent, and a record with neither is dropped.
- `api.py`: against recorded fixtures — the page-until-total loop fetches a
  second page when `total` exceeds `size`; a derived key that 404s falls back
  to `/api/file/metadata`; a failed quant fetch is counted, not raised.
- `shared/platemap.py`: `platemap_rows` keys on the platemap's `sample_no` and
  not on the row index, demonstrated on a map whose two differ; a row with a
  non-numeric coordinate is dropped whole; `plate_api_for_config` returns
  `None` for a config where no server declares `params.plate_api`, and finds
  the API when one does.

Reflex-level tests:

- `build_page()` is rendered, not merely imported. Event-binding mismatches
  (a handler bound to both a button and something that supplies an argument)
  raise at **render**, not at import, so an import-only test cannot see them.
- The non-numeric columns are filtered before reaching `plots`.
- `plots.ternary` returns a `ChartPayload` whose spec carries the expected
  trace count (points, three edges, three labels).

Existing tests that must still pass **unedited**, and which are the gate on the
hoist in §3.0: the xy-import isolation test, the palette AST sweep,
`test_standalone_operator.py` (59 tests), `test_reflex_operator.py`, and
`test_reflex_routes_e2e.py` — the last of which names
`OperatorPlateState: ("load_plate", "on_select", "set_sample")` explicitly and
will fail if the hoist disturbs the operator's state class.

## 8. Explicitly out of scope

- The Bokeh stack. No `/composition` equivalent, no shared document.
- Fixing `OpenAPIClient`'s summary-collision name derivation (§2.7). Worked
  around here; worth its own change.
- `stage_x`/`stage_y` as a coordinate fallback (§2.5).
- Changing `platemap_points`' positional sample numbering (§3.0). It is left
  exactly as it is; `platemap_rows` is added beside it. Whether the operator
  should be reading `sample_no` too is a separate question about the operator.
- A hover tooltip (§4).
- Any write path. This page reads; it creates, edits and deletes nothing.
- Elements-rather-than-transitions in the dropdowns, and any use of
  `fluorescence_priority.csv`, which lives in a private deployment this page
  must not import.
