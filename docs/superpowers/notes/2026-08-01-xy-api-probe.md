# xy / Reflex API probe — 2026-08-01

### Verified findings (recorded 2026-08-01, `helao` env, Python 3.14.6)

**Versions:** `reflex` 0.9.7, `xy` 0.0.5. Both Apache-2.0.

**`xy.reflex`:** absent. `importlib.util.find_spec("xy.reflex")` returns `None`. Not a naming difference — confirmed against xy's shipped source.

**xy submodules:** `channel`, `channels`, `columns`, `components`, `config`, `dom`, `export`, `facets`, `interaction`, `kernels`, `lod`, `marks`, `plugins`, `pyplot`, `styles`, `styling`, `widget`.

**xy chart breadth at 0.0.5** — wider than the README implies. Marks and chart constructors include: `line`/`line_chart`, `scatter`/`scatter_chart`, `bar`/`bar_chart`, `hist`/`histogram`/`histogram_chart`, `heatmap`/`heatmap_chart`, `contour`/`contour_chart`, `step`/`step_chart`, `stairs`/`stairs_chart`, `area`/`area_chart`, `box`/`box_chart`, `violin`/`violin_chart`, `ecdf`/`ecdf_chart`, `hexbin`/`hexbin_chart`, `errorbar`/`errorbar_chart`, `error_band`, `segments`, `stem`, `sankey`, `pie_chart`, `polar_chart`, `polar_bar_chart`, `radar_chart`, `wind_rose`, `triangle_mesh`, `contour`. Axis/annotation helpers: `x_axis`, `y_axis`, `r_axis`, `theta_axis`, `hline`, `vline`, `x_band`, `y_band`, `label`, `callout`, `legend`, `tooltip`, `colorbar`, `modebar`, `annotations`, `threshold`, `threshold_zone`.

Every chart HELAO's Bokeh visualizers draw has a direct counterpart. In particular `hist` exists, so histograms are native — do **not** fake them with step lines.

**Composition API:** `xy.chart(*children: Component, **props) -> Chart`. Declarative: marks and axes are child components, not method calls on a figure.

**The renderer, which is what makes the binding possible:**

- `xy.widget.bundled_js(which="widget"|"standalone") -> str` reads a bundled client build from `<xy package dir>/static/`. Both files ship in the wheel: `index.js` (ESM, ~411 KB) and `standalone.js` (IIFE, ~411 KB). xy's docstring is explicit that this is versioned and CDN-free for airgapped use.
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

Probe script (`conda run -n helao python scratchpad/probe_xy.py`):

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

## Consequences for the implementation

- There is no `xy.reflex`. `helao/core/servers/reflex/xy_component.py` (Task 4) is the
  HELAO-written binding, built on `bundled_js`, `build_payload_split`, and `xy.channel`.
  Delete it when xy ships its own adapter.
- Histograms are native (`xy.hist`). Do not fake them with step lines.
- The ESM asset ships inside the wheel. The launcher copies it to the frontend build;
  nothing fetches from a CDN, which is what airgapped lab stations need.
- Re-run the probe after any version bump and update this note.
