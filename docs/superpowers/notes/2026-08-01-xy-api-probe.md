# xy / Reflex API probe — 2026-08-01

### Verified findings (recorded 2026-08-01, `helao` env, Python 3.14.6)

**Versions:** `reflex` 0.9.7, `xy` 0.0.5. Both Apache-2.0.

**`xy.reflex`:** absent. `importlib.util.find_spec("xy.reflex")` returns `None`. Not a naming difference — confirmed against xy's shipped source.

**xy submodules** (regenerated from this run's `SUBMODULES:` probe line, via `pkgutil.iter_modules(xy.__path__)`; matches the prior recording exactly): `channel`, `channels`, `columns`, `components`, `config`, `dom`, `export`, `facets`, `interaction`, `kernels`, `lod`, `marks`, `plugins`, `pyplot`, `styles`, `styling`, `widget`.

**xy chart breadth at 0.0.5** — regenerated from this run's `EXPORTS:` probe line (`dir(xy)`), not transcribed. **This corrects the previous version of this note**, which spot-checked 8 marks by name and never enumerated the module: the earlier chart-breadth paragraph omitted `column`/`column_chart`, `facet_chart`, `arrow`, `ribbon`, `marker`, and `text` entirely, and listed `error_band`, `segments`, `stem`, `sankey`, and `triangle_mesh` as bare-only when xy 0.0.5 also ships a `_chart` sibling for each (`error_band_chart`, `segments_chart`, `stem_chart`, `sankey_chart`, `triangle_mesh_chart`) — 12 names added by this correction. Every name below is verified present in the `EXPORTS:` line reproduced verbatim in the Probe output section. Marks and chart constructors: `line`/`line_chart`, `scatter`/`scatter_chart`, `bar`/`bar_chart`, `column`/`column_chart`, `hist`/`histogram`/`histogram_chart`, `heatmap`/`heatmap_chart`, `contour`/`contour_chart`, `step`/`step_chart`, `stairs`/`stairs_chart`, `area`/`area_chart`, `box`/`box_chart`, `violin`/`violin_chart`, `ecdf`/`ecdf_chart`, `hexbin`/`hexbin_chart`, `errorbar`/`errorbar_chart`, `error_band`/`error_band_chart`, `segments`/`segments_chart`, `stem`/`stem_chart`, `sankey`/`sankey_chart`, `triangle_mesh`/`triangle_mesh_chart`, `pie_chart`, `polar_chart`, `polar_bar_chart`, `radar_chart`, `wind_rose`, `facet_chart`, `arrow`, `ribbon`, `marker`, `text`. Axis/annotation helpers: `x_axis`, `y_axis`, `r_axis`, `theta_axis`, `hline`, `vline`, `x_band`, `y_band`, `label`, `callout`, `legend`, `tooltip`, `colorbar`, `modebar`, `annotations`, `threshold`, `threshold_zone`.

Every chart HELAO's Bokeh visualizers draw has a direct counterpart. In particular `hist` exists, so histograms are native — do **not** fake them with step lines.

**Composition API:** `xy.chart(*children: Component, **props) -> Chart`. Declarative: marks and axes are child components, not method calls on a figure.

**The renderer, which is what makes the binding possible:**

- `xy.widget.bundled_js(which="widget"|"standalone") -> str` reads a bundled client build from the installed xy package's `static/` directory, resolved at runtime as `pathlib.Path(xy.widget.__file__).parent / "static"` (this probe's env resolves it to `.../site-packages/xy/static`). Both files ship in the wheel: `index.js` (ESM, ~411 KB) and `standalone.js` (IIFE, ~411 KB). xy's docstring is explicit that this is versioned and CDN-free for airgapped use.
- `Figure.build_payload_split(px_width: Optional[int] = None) -> tuple[dict, list[memoryview]]` — a data-less JSON spec plus raw per-column binary buffers. xy documents this same split layout as serving both first paint **and streaming append**.
- `xy.channel` exposes the wire protocol: `encode_frame`, `encode_frame_parts`, `decode_frame`, `handle_message`, `FRAME_MAGIC`, `FRAME_VERSION`, `FRAME_HEADER_SIZE`, `FRAME_ALIGNMENT`, `FrameDecodeError`, `FrameEncodeError`, `FrameLimits`, `DEFAULT_FRAME_LIMITS`, `Reply`, `DecodedFrame`, `Selection`, `normalize_window`, `SELECTION_EVENT_ID_LIMIT`, `SELECTION_EVENT_ROW_LIMIT`.
- `xy.widget.FigureWidget` (anywidget) shows the intended contract: traits `spec` (Dict, synced) and `buffers` (Any, synced as raw binary), plus callbacks `on_hover`, `on_click`, `on_brush`, `on_select`, `on_view_change`, `on_animation_start`, `on_animation_end` wired through `ChannelCallbacks` and `handle_message`.

**Reflex 0.9.7 capabilities Tasks 4-10 depend on** — all confirmed present: `rx.data_table`, `rx.card`, `rx.badge`, `rx.cond`, `rx.State`, `App.register_lifespan_task`, `rx.NoSSRComponent`, and `rx.Component`'s `library` / `tag` / `add_imports` / `_get_custom_code` / `is_default` / `lib_dependencies` wrapping surface.

## Probe output

Installed versions (`conda run -n helao pip show reflex xy`):

```
Name: reflex
Version: 0.9.7
License: Apache-2.0
Name: xy
Version: 0.0.5
License: Apache-2.0
```

Probe script (`conda run -n helao python probe_xy.py`, run from the scratchpad — never the repo) — this version adds the
`SUBMODULES:`/`EXPORTS:` enumeration lines that the note's two regenerated lists above are
derived from, replacing the earlier version that only spot-checked 8 mark names:

```python
import importlib.util as u
import inspect
import pathlib

import reflex as rx
import xy
import xy.channel
import xy.widget

print("reflex", getattr(rx, "__version__", "?"))
print("xy", getattr(xy, "__version__", "?"))
print("xy.reflex spec:", u.find_spec("xy.reflex"))

static = pathlib.Path(xy.widget.__file__).parent / "static"
print("static dir exists:", static.exists())
for f in sorted(static.iterdir()) if static.exists() else []:
    print("  asset:", f.name, f.stat().st_size)

print("chart signature:", inspect.signature(xy.chart))
print("build_payload_split:", inspect.signature(xy._figure.Figure.build_payload_split))
print("bundled_js:", inspect.signature(xy.widget.bundled_js))

# Enumerate rather than spot-check: the note's submodule and chart-breadth
# lists are what Tasks 4-7 call xy by, so they must be derived from real
# output, never transcribed by hand.
import pkgutil

print("SUBMODULES:", ",".join(
    sorted(m.name for m in pkgutil.iter_modules(xy.__path__)
           if not m.name.startswith("_"))))
print("EXPORTS:", ",".join(sorted(n for n in dir(xy) if not n.startswith("_"))))

for name in ("line", "scatter", "bar", "hist", "heatmap", "step", "x_axis", "y_axis"):
    print(f"xy.{name}:", hasattr(xy, name))

for name in ("encode_frame_parts", "decode_frame", "handle_message", "Selection"):
    print(f"xy.channel.{name}:", hasattr(xy.channel, name))

for name in ("data_table", "card", "badge", "cond", "State", "NoSSRComponent"):
    print(f"rx.{name}:", hasattr(rx, name))
print("App.register_lifespan_task:", hasattr(rx.App, "register_lifespan_task"))
```

Verbatim stdout:

```
reflex ?
xy 0.0.5
xy.reflex spec: None
static dir exists: True
  asset: index.js 411642
  asset: standalone.js 411751
chart signature: (*children: 'Component', **props: 'Any') -> 'Chart'
build_payload_split: (self, px_width: 'Optional[int]' = None) -> 'tuple[dict[str, Any], list[memoryview]]'
bundled_js: (which: 'str' = 'widget') -> 'str'
SUBMODULES: channel,channels,columns,components,config,dom,export,facets,interaction,kernels,lod,marks,plugins,pyplot,styles,styling,widget
EXPORTS: Animation,Annotation,Any,Axis,CHART_DOM_SLOTS,Chart,Colorbar,Column,ColumnStore,Component,Engine,ExportConfig,FacetChart,Interaction,Legend,Mark,MarkContext,MarkPlugin,Modebar,Selection,Spring,TYPE_CHECKING,Theme,Tooltip,ZoneMaps,animation,annotations,area,area_chart,arrow,bar,bar_chart,box,box_chart,callout,channel,channels,chart,colorbar,column,column_chart,columns,components,config,contour,contour_chart,dom,ecdf,ecdf_chart,error_band,error_band_chart,errorbar,errorbar_chart,export,export_config,facet_chart,heatmap,heatmap_chart,hexbin,hexbin_chart,hist,histogram,histogram_chart,hline,import_module,interaction,interaction_config,kernels,label,legend,line,line_chart,lod,mark,marker,marks,modebar,pie_chart,plugins,polar_bar_chart,polar_chart,r_axis,radar_chart,register_mark,registered_marks,ribbon,sankey,sankey_chart,scatter,scatter_chart,segments,segments_chart,spring,stairs,stairs_chart,stem,stem_chart,step,step_chart,styles,text,theme,theta_axis,threshold,threshold_zone,tooltip,triangle_mesh,triangle_mesh_chart,unregister_mark,violin,violin_chart,vline,widget,wind_rose,write_images,x_axis,x_band,y_axis,y_band
xy.line: True
xy.scatter: True
xy.bar: True
xy.hist: True
xy.heatmap: True
xy.step: True
xy.x_axis: True
xy.y_axis: True
xy.channel.encode_frame_parts: True
xy.channel.decode_frame: True
xy.channel.handle_message: True
xy.channel.Selection: True
rx.data_table: True
rx.card: True
rx.badge: True
rx.cond: True
rx.State: True
rx.NoSSRComponent: True
App.register_lifespan_task: True
```

Note: `reflex` has no `__version__` attribute at import time (probe prints `?` for that line);
the exact version is confirmed instead via `pip show reflex` above (0.9.7).

`SUBMODULES:` and `EXPORTS:` are the source of truth for the "xy submodules" and "xy chart
breadth" lists earlier in this note — every name in those two prose lists traces to one of
these two lines, not the other way around. The `EXPORTS:` line also contains submodule names
(`channel`, `channels`, `columns`, `components`, `config`, `dom`, `export`, `interaction`,
`kernels`, `lod`, `marks`, `plugins`, `styles`, `widget` — bound onto `xy` because something in
its import chain imports them) and a handful of non-chart plumbing names (`chart` — the
composition entrypoint documented separately above; `mark`/`register_mark`/`unregister_mark`/
`registered_marks` — the mark-plugin registry, not a chart type; `animation`/`spring` — transition
helpers; `interaction_config`/`export_config` — config functions; `theme` — theming, not a chart;
`import_module` — a stdlib re-export leaking through `xy`'s `__init__.py`; `write_images` — an
export-pipeline helper). None of those are chart/mark constructors or axis/annotation helpers, so
they are correctly excluded from the chart-breadth paragraph above.

## Consequences for the implementation

- There is no `xy.reflex`. `helao/core/servers/reflex/xy_component.py` (Task 4) is the
  HELAO-written binding, built on `bundled_js`, `build_payload_split`, and `xy.channel`.
  Delete it when xy ships its own adapter.
- Histograms are native (`xy.hist`). Do not fake them with step lines.
- The ESM asset ships inside the wheel. The launcher copies it to the frontend build;
  nothing fetches from a CDN, which is what airgapped lab stations need.
- Re-run the probe after any version bump and update this note.

## Exact call signatures, verified during Task 4

The findings above record which names exist. These record how to *call* them —
established by running each against the installed package while implementing
the facade. The plan's original snippets got all five of these wrong, and the
first would have raised on first real use rather than at import.

| Call | Correct form | What was wrong before |
|---|---|---|
| Payload split | `xy.chart(...).figure().build_payload_split()` | `xy.chart()` returns a **`Chart`**, not a `Figure`. `Chart` has no `build_payload_split`; the data-less `Figure` is produced lazily by `.figure()`. |
| Frame encoding | `xy.channel.encode_frame_parts(meta_mapping, buffers)` → parts | Takes a JSON-able metadata mapping as its first argument, and returns scatter/gather **parts**, not one `bytes` blob. Join them. |
| Series label | `xy.line(..., name=...)`, `xy.scatter(..., name=...)`, `xy.hist(..., name=...)` | Not `label=`. |
| Histogram data | `xy.hist(values=..., bins=...)` | Not `x=`. |
| Time axis | `xy.x_axis(label=..., type_="time", format="%H:%M:%S")` | Not `scale=` / `tick_format=`. |

Re-run the Task 0 probe *and* re-check these kwargs after any xy version bump;
the names surviving does not imply the signatures did, on a 0.0.x dependency.

## Exact call signatures, verified during Task 7

`xy.text` and `xy.line`, needed to assemble a ternary diagram (xy 0.0.5 ships
no ternary mark; `polar_chart`/`radar_chart` are a different projection):

```
xy.text(x: CoordinateLike, y: CoordinateLike, value: str, *, dx=6.0, dy=-6.0,
        color=None, anchor='start', class_name=None, style=None) -> Annotation
xy.line(x=None, y=None, *, data=None, name=None, color=None, width=1.5, ...) -> Mark
```

**`xy.text` is an `Annotation` constructor, not a `Mark` one.** It takes
scalar `x`/`y` and a single `value` string (no per-point arrays, no `name`),
and `Figure.build_payload_split` places it under the spec's `annotations`
key, not `traces`. A diagram with 3 vertex labels and a populated point cloud
therefore publishes 4 `traces` (1 scatter + 3 edge lines) and 3
`annotations` — not 7 traces, which is what you'd expect from treating
`xy.text` as a mark.

## Verified for the /group page (2026-11-06, xy 0.0.8)

Probe: a scratch script asserting each fact below (run with the helao env python).

| Fact | Consequence |
|---|---|
| `xy.scatter(symbol=...)` takes `"triangle"` and `"triangle_down"`; `"triangle-down"` raises `ValueError` from `build_payload_split`, not at construction | arrowheads and pulses use the underscore names |
| a per-point `color=[hex, ...]` list encodes as `direct_rgba` column data | node, arrow and pulse colours update in place, no rebuild |
| an **empty** `color=[]` encodes as `continuous` (viridis), not `direct_rgba` | `plots.marks_chart` pads an empty trace with one off-domain point so its column layout never changes |
| a `size` array is a mapped channel (`range_px (2, 18)`), not pixels | one scalar size per trace |
| `x_axis(show=False, grid=False, domain=...)` only paints the axis transparent (colours `#00000000`); it does NOT remove it from layout | alone it still reserves tick-label room: bottom at least `max(padding[2], 42)` (36 when narrow), left at least the tick-label width |
| `x_axis(..., tick_label_strategy="none")` (same on `y_axis`) lands in `spec["axes"][...]["tick_label_strategy"]` and `_layout` then skips the axis room | graph and strips hide axes with `show=False, grid=False, tick_label_strategy="none"` |
| `xy.chart(..., pan=False, zoom=False, click=True)` lands in `spec["interaction"]` | fixed view; clicks still reach `on_select` |
| `xy.text(..., anchor="middle")`, `x_band` (`band`) and `vline` (`rule`) are annotations, not traces | they are spec, so `plots.ANNOTATIONS_IN_TOKEN` decides whether a changed label rebuilds the chart |
| a chart of annotations only has zero traces | each strip carries an invisible `hit` scatter |
| `xy.chart(padding=[top, right, bottom, left])` lands in `spec["padding"]` and `_layout` uses it as the plot-rect margin px, provided the axes also carry `tick_label_strategy="none"` | netgraph takes the inset as a parameter, defaulting to its `padding` (8 px each side in the probe); confirm in a browser in Task 9 |

Plot-area inset (host edge to plot rect): with `show=False` alone it is NOT the padding. `_layout` still reserves tick-label room (bottom `max(padding[2], 42)`, 36 when narrow, i.e. about 34 px more than an 8 px padding; left includes the tick-label width). With `tick_label_strategy="none"` on both axes, `_layout` reads as inset = padding (top `padding[0]`, right `padding[1]`, bottom `padding[2]`, left `padding[3]`), except on a fluid (`width="100%"`) host narrower than 520 px, where right is `min(padding[1], 8)` and left `min(padding[3], 46)`. This is from reading the minified `_layout`, not a browser measurement: Task 9 must measure it, and netgraph must take the inset as a parameter.

Browser outcome (2026-11-06, Task 9 and the final-wave re-check, headless Chromium): xy applies a changed annotation (text label, `x_band` colour, `vline` position) in place on an append, with no rebuild, so `plots.ANNOTATIONS_IN_TOKEN` is False. Charts are laid out at least 120 px tall whatever the host reserves, but only in fluid-height mode (`height="100%"`: `standalone.js` has `fluidH = height === "100%"` and `size.h = Math.max(fluidH ? 120 : 48, o)`). A fixed pixel height is floored at 48, so `marks_chart(height_px=...)` lets `STRIP_H` be 60. Text annotations are DOM elements (`data-xy-slot="annotation_label"`, 11 px, `width:max-content`), so `style` with `max_width`, `overflow: hidden`, `text_overflow: ellipsis`, `white_space: nowrap` truncates them in the browser.

Hover, tooltip and rebuilds (2026-11-06, xy 0.0.8, read from `static/index.js` and confirmed in headless Chromium):

| Fact | Consequence |
|---|---|
| the hover highlight (`_drawHoverPoint`) never sets `u_symbol`, so it is drawn with the symbol of the LAST scatter trace drawn that frame; colour, size and opacity come from `mark_style.hover` (chart-wide, one colour; defaults `max(1.75*size, size+5)` px, `rgba(15,23,42,.92)`, 0.95) | a pulse trace drawn last hovered as a big dark `triangle_down`; a highlight cannot take the point's own colour |
| `mark_style` is reachable only as `chart.figure().set_mark_style(hover={"opacity": 0.0})` (not in the declarative API); `figure()` is cached, so `_publish` ships it | `marks_chart(hover_events=True)` makes the highlight fully transparent |
| `xy.chart(hover=True)` lands in `spec["interaction"]`; the client then dispatches a bubbling `xy:hover` DOM event whose `detail.points[0]` is `{trace: <mark name>, index, ...}`, only when the point under the pointer CHANGES; the hovered point is the pixel-exact pick, else the nearest point of any trace within 12 px | the shim forwards `{trace, index}` to Reflex (`on_hover`) |
| no event for moving from a point onto empty plot; `xy:leave` fires only when the pointer leaves the chart | the shim watches the tooltip element (`data-xy-slot="tooltip"`): xy sets `display:none` on it in exactly that case |
| `figure.show_tooltip = False` (== `xy.tooltip(show=False)`) removes the readout but also keeps the tooltip element hidden forever, so the leave signal above is lost; `xy.tooltip(style={"opacity": "0", "pointer_events": "none"})` lands in `spec["dom"]["styles"]["tooltip"]` and hides it visually while xy still toggles `display` | strips: tooltip invisible, not disabled. The /group graph no longer uses either: see the pointer row below |
| a `size` array is a mapped channel (2-18 px), so one node cannot be drawn larger inside the node trace | the graph's hover circle is drawn by the browser (`xy_component` overlay canvas, `nodes` descriptors, radius `HOVER_PX/2`), not by a trace; the old server-side one-point `hovered` scatter is gone |
| no per-trace hover switch: pick is a pixel pass over every point trace | strips only: the graph takes no xy hover (below) and hit-tests nodes itself, so a crossing pulse is irrelevant to it |
| a layout-token change (here a line's colour or width) rebuilds the chart: `rm`/`add` of 3 canvases plus a 155 ms main-thread long task, during which ticks stop | graph edges are one fixed `xy.segments` trace per (colour, width) style; a status change only moves segments between traces. (A NaN-joined `line` trace was tried first: xy draws a straight connector across the NaN, a stray diagonal between edges.) |
| `xy.animation(...)` / `scatter(animation=...)` exists (match index, interpolate position); unused: 38-43 distinct positions per 1.2 s pulse without it | revisit if a slow client still looks choppy |
| an in-place update whose point POSITIONS are unchanged does not repaint a changed colour column (measured: a busy node stayed its idle colour after the layout token stopped changing; a trace whose x/y also changed, such as a pulse, repaints fine) | node traces exist per colour and points move between them, like the edges; this corrects the older row saying per-point colours "update in place, no rebuild" |
| the strips' hover leave signal (tooltip element hidden) and the `xy:hover` payload shape are read from xy 0.0.8's client internals: re-check both on any xy upgrade. Measured: xy does NOT hide the tooltip on in-place data updates | `_hover_strip` clears only on an empty trace or index -1 |
| xy tracks `_hoverTarget` on every pointer move even with `hover` unset or false and the tooltip off, draws its dark highlight ring, and `_drawHoverPoint` throws `Cannot read properties of null (reading '_fcId')` when the hovered node's trace buffers were swapped by a status-colour change; the page then reloads (3 of 3 runs). Re-check on any xy upgrade | `marks_chart` with neither `hover_events` nor `click` sets `dom.style.pointer_events = "none"` on the xy root, so xy never sees the pointer; the host div still does, which is where the graph's own hover listens (browser hit-test against `nodes` descriptors, circle on the overlay canvas) |
| xy's labels are `[data-xy-slot="labels"]`, an absolutely positioned inset child of xy's root (`position: relative`); an overlay canvas appended after the root draws over the label text | the overlay canvas is inserted directly before the labels layer, re-checked on every draw. Re-check the slot name and nesting on any xy upgrade |

xy 0.0.8 in-place append and hover on strips (2026-11-06, read from `static/index.js` `_appendTraceInPlace`, confirmed in headless Chromium):

| Fact | Consequence |
|---|---|
| a scatter/line trace updates in place only if its length is >= the old one AND its x/y column offset+scale are unchanged; it then writes ONLY the points past the old length (prefix kept). Any other change rebuilds the trace. `segments` always rebuild | a node joining a colour trace ahead of its siblings (orch busy -> idle with every server idle) left stale copies of the siblings and no node: the ORCH vanished with its label still drawn (3 of ~20 runs). Node traces are now one trace per (node, colour) of ONE point, the node or the off-domain placeholder, so a change swaps offsets and xy rebuilds; `test_xy_repaints_every_node_after_any_status_change` models this rule over every status pair |
| hover pick is pixel-exact on a drawn marker, not "nearest within 12 px" (4 px hit circles reported a hover and left a frame later) | strips' invisible `hit` trace is a 60 x 7 grid of 16 px squares that tile the plot; `timeline_strip.hit_slot` maps a grid index back to its slot |
| xy's modebar sits invisibly over the chart's top-left corner and swallows the pointer there (no hover or click on a strip's first slots) | `marks_chart` adds `xy.modebar(show=False)` |
| pulses computed on the server at 60 Hz measured ~40 positions per 1.2 s pulse (about 33 fps, uneven): each frame is a tick, a state delta, a buffer fetch and an xy repaint | pulses animate in the browser (canvas overlay in the shim, rAF): measured 60.8-61.0 fps over 72 draws per 1.2 s pulse, gap stdev 0.5-1.3 ms, max gap ~21 ms, 0 graph rebuilds, no long task from pulses (2026-11-06, headless Chromium) |
