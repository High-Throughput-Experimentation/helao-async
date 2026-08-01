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
