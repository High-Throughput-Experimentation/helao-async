# Reflex UI stack — design

**Date:** 2026-08-01
**Status:** approved, awaiting implementation plan
**Scope of this spec:** the Reflex/xy skeleton plus the `test` deployment visualizers. The operator page is explicitly out of scope and gets its own spec.

## Problem

The Bokeh operator and visualizers hit three ceilings at once:

1. **UI/UX.** Bokeh's widget set and `layout()` model are rigid. No real CSS control, no responsive layout, no multi-page navigation.
2. **Plot performance.** Plate maps (`sample_vis`, the operator's plate-map figure), `spec_vis` spectra, `data_browser` run trees, and live streaming plots are all reported slow.
3. **Development experience.** `bokeh_operator.py` is 3076 lines in one class. Visualizers carry imperative `ColumnDataSource` / `add_next_tick_callback` / `layout()` churn that resists extension.

Current surface: ~7.8k lines. `helao/core/servers/operator/bokeh_operator.py` (3076), `helao/core/servers/vis_subscriber.py` (432), `bokeh_launcher.py` (210), `helao/core/servers/vis.py` (91), 14 `hte` visualizers (181–392 each), 3 `test` visualizers.

## Viability assessment

Reflex is a viable full-stack alternative. It is a FastAPI backend plus a compiled Next.js frontend with WebSocket state sync — structurally the same server-push model HELAO already gets from Bokeh Server. A Reflex per-session `State` maps onto a Bokeh per-session `Document`; event handlers map onto the existing `callback_*` methods; `@rx.event(background=True)` tasks map onto `IOloop_data`. Reflex's native widgets cover everything `bokeh_operator.py` uses.

Two costs are real and are addressed below:

- Reflex needs Bun/Node at **build** time. Bokeh needs only `pip`. Lab Windows stations may have neither Node nor internet.
- The frontend is a compiled artifact, so layout changes are not covered by the existing Python hot-reload watcher.

`xy` (`reflex-dev/xy`) is a Rust/WebGL2 charting library. It is **pre-1.0 alpha** (0.0.5 at time of writing) and its own documentation states that "callback payloads, the Reflex adapter, chart breadth ... may change."

A probe of the installed 0.0.5 wheel corrected two things the published README implied:

- **Chart breadth is wide, not narrow.** 0.0.5 exports `line`, `scatter`, `bar`, `hist`/`histogram`, `heatmap`, `contour`, `step`, `stairs`, `area`, `box`, `violin`, `ecdf`, `hexbin`, `errorbar`, `sankey`, `pie`, and polar/radar families. Every chart HELAO's Bokeh visualizers draw has a direct counterpart.
- **There is no Reflex adapter.** `xy.reflex` does not exist. xy's own source calls the Reflex adapter planned, unshipped work. This is the load-bearing correction: the integration cannot be `pip install "xy[reflex]"`.

What xy *does* ship is the renderer the adapter would have wrapped:

- `xy/static/index.js` — a 411 KB ESM client build, and `standalone.js`, its IIFE twin. Both ship inside the wheel, versioned, **no CDN**, which is what an airgapped lab station needs.
- `Figure.build_payload_split(px_width) -> (spec: dict, buffers: list[memoryview])` — a small data-less JSON spec plus raw per-column binary buffers, explicitly documented as the layout used for both first paint and **streaming append**.
- `xy.channel` — a defined binary frame protocol (`encode_frame`, `decode_frame`, `handle_message`, `FRAME_MAGIC`, `FRAME_VERSION`) and a `Selection` payload for hover/click/brush/select/view-change callbacks.

So HELAO writes the Reflex binding itself (Decision 7). Reflex supplies everything needed to do that: `rx.NoSSRComponent` for a client-only WebGL component, plus `library` / `add_imports` / `_get_custom_code` for wrapping a local ESM asset.

One honest caveat on performance: today's live visualizers cap at `max_points` 10000 (`vis_subscriber.py`), default 500. Bokeh is not slow at 10k points, so xy's large-dataset advantage does not by itself explain live-plot stutter. The stutter is addressed architecturally by decoupling ingest rate from render rate; xy's advantage lands on `spec_vis`, plate maps, `data_browser`, and on raising the buffer depth far past 10k.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **Coexist indefinitely** with Bokeh | Additive. The Bokeh path is untouched; stations opt in per config. No forced cutover, no production blast radius. |
| 2 | **One Reflex app, multi-page routes** per orchestration group | One process, one port, one frontend build. Running one Reflex app per config entry would mean 4 Next.js builds and 4 processes per station. |
| 3 | **Process-wide ingest with ring buffers** | One WebSocket per action server for the whole process instead of N sessions × M servers. Decouples ingest rate from render rate. |
| 4 | **Thin plot facade over xy** | xy is alpha. All charts call a small HELAO API; xy sits behind it, version-pinned. An upstream break touches one file, not 14. |
| 7 | **HELAO writes the Reflex binding for xy** | `xy.reflex` does not exist at 0.0.5, but xy's ESM renderer, split spec/buffer payload, and binary channel protocol all ship in the wheel. Writing the binding is the only path that keeps live streaming *at xy's speed*; the alternatives (HTML-export embedding, or Reflex-native charts) each give up the plot-performance win that motivated the project. The binding is expected to become redundant when xy ships its own adapter — it is deliberately confined to two files so it can be deleted. |
| 8 | **Bulk column data travels over HTTP, not Reflex state** | Reflex syncs state as JSON over its WebSocket. Pushing megabyte float arrays through that channel would forfeit exactly the performance xy exists to provide. The spec (small JSON) rides Reflex state; the binary column buffers are fetched by the browser from a HELAO backend route, straight from the ring buffer's numpy memory. |
| 5 | **Prebuilt frontend artifact, runtime fallback to build** | Stations never invoke Node. Dev machines still get a one-command local build. |
| 6 | **First slice = `test` deployment visualizers only** | Runs on Linux, no hardware gate, exercises both `ws_live` and `ws_data`. Verifiable without a station. |

## Architecture

### Coexistence seam

A server entry opts in with a new `reflex:` key, mutually exclusive with `fast:` and `bokeh:`:

```yaml
helao_ui:
  group: visualizer
  host: 127.0.0.1
  port: 5010
  reflex: helao_ui
  params:
    pages: [live, action]
```

`launch.py` validation is extended to require exactly one of `fast:` / `bokeh:` / `reflex:` per server entry. `LAUNCH_ORDER` is unchanged — Reflex servers live in the existing `visualizer` and `operator` groups. PIDs are written to the same `STATES/pids_<prefix>_<extraopt>.pck`; teardown uses the same POST `/shutdown` plus `psutil` termination.

### New files

| Path | Role |
|---|---|
| `reflex_launcher.py` | Sibling of `bokeh_launcher.py`. Resolves the prebuilt frontend bundle, starts the Reflex backend, writes the loaded-modules snapshot for the hot-reload watcher. |
| `helao/core/servers/reflex/app.py` | Builds the single `rx.App`; registers one route per entry in `params.pages`, composing panels from the config `servers:` block. |
| `helao/core/servers/reflex/ingest.py` | `RingBuffer`, `WsIngest`, `IngestRegistry`. |
| `helao/core/servers/reflex/xy_component.py` | The Reflex binding: an `rx.NoSSRComponent` wrapping xy's shipped ESM client, plus the FastAPI route serving column buffers. Deletable once xy ships its own adapter. |
| `helao/core/servers/reflex/plots.py` | The plot facade. The only module that imports `xy`. |
| `helao/core/servers/reflex/state.py` | `LiveVisState` / `ActionVisState` base classes. |
| `helao/deploy/<deployment>/servers/reflex/*.py` | Per-instrument page modules, mirroring `servers/visualizer/`. |

### Module discovery

Reflex page modules are resolved through the same `live_vis:` / `action_vis:` config keys and the same deployment search order that `vis_subscriber.import_vis_class` uses today. That search-order logic (`_deployment_search_order`) is lifted into a shared helper so the Bokeh and Reflex paths cannot drift apart. Where a Bokeh module exposes `C_vis`, a Reflex module exposes `panel(server_key) -> rx.Component` and a `PanelState`.

### Routes

`/` (index), `/operator`, `/live`, `/action`, `/browser`. A station with three live-vis servers gets one `/live` page stacking three panels — the same composition `mount_visualizers` performs today, expressed as a route instead of a port.

Only `/live` and `/action` are implemented by this spec. `/` renders a route index. `/operator` and `/browser` are registered as placeholder routes so the navigation shell is complete; their content lands in later specs.

### Build and deployment

`reflex export --frontend-only` on a development machine produces a static bundle. The bundle ships as a release artifact and is **gitignored**, not committed. `reflex_launcher.py` serves the bundle if present and never invokes Node on a station. If no bundle is present and Node/Bun is available, it builds locally as a developer convenience; if neither is available, it fails with an explicit error naming the missing bundle path.

Hot-reload: Python-only edits behave as they do for Bokeh servers today, via the loaded-modules snapshot. Frontend layout changes require a rebuild; the launcher logs the bundle's build stamp at startup so a stale bundle is visible.

## Data flow

```
action server ws_live / ws_data
        │  one WsIngest task per (server_key, ws_path), process-wide
        ▼
   RingBuffer — columnar numpy, fixed capacity
        │  per-session render loop at user-settable rate
        ▼
   Reflex State vars → xy chart component
```

### RingBuffer

Columnar numpy storage with `append(cols: dict[str, array])` and `snapshot(n) -> dict[str, array]`. Default capacity 1,000,000 rows, configurable per panel. Because xy renders only visible pixels, buffer depth is no longer a performance knob: the existing "max datapoints" input becomes a *display window* selector rather than a memory cap. Overflow drops oldest rows, by design.

### WsIngest

Wraps the existing `helao.helpers.ws_utils.WsSubscriber`. One asyncio task per `(server_key, ws_path)`, started at app startup from the config and alive for the process lifetime. It drains messages, normalizes them into columns, and appends to the ring buffer.

It **reconnects with exponential backoff**. This closes a known gap: today a restarted action server silently kills a visualizer's feed with no reconnect and no user-visible indication.

### IngestRegistry

Process-wide registry mapping `(server_key, ws_path)` to a single `WsIngest`. Constructed once at app startup from the config; not reference-counted, not lazily torn down. Every browser session reads the same buffers.

### Render decoupling

Ingest runs at WebSocket speed. Rendering is a per-session `@rx.event(background=True)` loop at a user-settable rate (default 2 Hz) that calls `snapshot()` and assigns to State vars. Today `IOloop_data` schedules a `doc.add_next_tick_callback` per WebSocket batch, so render is hostage to ingest — this is the architectural fix for live-plot stutter.

## The xy Reflex binding

`helao/core/servers/reflex/xy_component.py` is the binding xy has not yet shipped. It has three parts.

**The component.** An `rx.NoSSRComponent` (client-only — a WebGL canvas cannot server-side render) that loads xy's `static/index.js` ESM. The asset is copied out of the installed wheel at build time, so the browser fetches it from the HELAO frontend and never from a CDN. It takes two props: `spec`, a Reflex state var holding the small data-less JSON from `build_payload_split`, and `buffer_url`, the route to fetch column data from. It emits xy's callbacks (`on_select`, `on_click`, `on_view_change`) as Reflex events, decoding the `Selection` payload on the Python side with `xy.channel`.

**The buffer route.** A FastAPI route on the Reflex backend, `GET /xy/buffers/{panel_id}?v={version}`, returning `application/octet-stream`. It serves the `list[memoryview]` from `build_payload_split` using `xy.channel.encode_frame_parts`, so the wire format is xy's own rather than something HELAO invented. Because `RingBuffer` is already numpy, producing those buffers is a `tobytes()` away — no serialization pass, no JSON number formatting.

**The version token.** The render loop assigns `spec` (small, cheap) into Reflex state, carrying a monotonic `version`. The component refetches buffers only when `version` changes. This is what keeps bulk data off Reflex's JSON WebSocket while still driving updates from ordinary Reflex state.

The binding is deliberately confined to this one module plus its asset-copy step in the launcher, so that when xy ships `xy.reflex` the deletion is mechanical: `plots.py` switches its private helpers to the upstream adapter and this file goes away.

## Plot facade

`helao/core/servers/reflex/plots.py` is the only module that imports `xy`. Four functions cover all existing visualizers:

| Function | Covers |
|---|---|
| `time_series(x, series, **opts)` | co2, mfc, temp, pressure, tec, power_supply, syringe, nidaqmx, gamry, biologic, wssim |
| `spectra(x, traces, **opts)` | spec_vis |
| `scatter_map(x, y, on_select=..., **opts)` | sample_vis, the operator plate map, oersim |
| `histogram(values_by_label, **opts)` | gpsim |

Functions take plain numpy arrays, not buffers, so the facade is testable with synthetic data and no ingest layer present. Each returns an `rx.Component` built through the binding above. `histogram` uses xy's native `hist` mark — the earlier plan to fake histograms with step lines was based on a mistaken reading of xy's chart breadth and is dropped.

The xy version is pinned in `helao_dev_linux-64.yml` and `helao_dev_win-64.yml`. Swapping the plotting backend means editing this one file plus the binding.

Tables use native `rx.data_table`; xy is not involved in tabular display.

## State model

`LiveVisState` and `ActionVisState` are the Reflex analogues of `LiveVisualizer` and `ActionVisualizer`. They carry `max_points`, `update_rate`, the render loop, and connection status. A per-instrument module subclasses one of them and supplies the data-specific column transform — the direct analogue of today's `add_points`.

## Error handling

| Condition | Behavior | Change from today |
|---|---|---|
| Target server absent from config | Panel renders a disabled placeholder stating the missing server key | Today: silent early return via `self.connected = False`, blank page |
| WebSocket drop | Ingest retries with backoff; panel shows a "reconnecting" badge | Today: no reconnect, feed dies silently |
| xy import or API failure | Facade raises at import; launcher logs and refuses to start | Prevents serving half-rendered pages |
| xy ESM asset missing from the wheel | Launcher fails at startup naming the expected `static/index.js` path and the `npm ci && node js/build.mjs` fix xy documents | The asset is a generated artifact; a source-checkout install lacks it |
| Buffer route requested for an unknown or stale `panel_id`/`version` | Returns 404; the component keeps its last good frame rather than blanking | A refetch racing a panel teardown must not clear a live chart |
| Ring buffer overflow | Oldest rows dropped | By design |
| Prebuilt bundle missing and no Node | Launcher fails with an explicit error naming the expected bundle path | New failure mode, made loud |

## Testing

**Unit**
- `RingBuffer` append / snapshot / rollover — pure numpy, no IO.
- `launch.py` validation: exactly one of `fast:` / `bokeh:` / `reflex:`; duplicate `host:port` still rejected.
- Config → route list and panel composition.
- Plot facade returns a component for each of the four functions against synthetic data.
- Binding: `build_payload_split` output round-trips through `xy.channel.encode_frame_parts` and decodes back to the same arrays; the version token increments only when data changes.

**Integration**
- `WsIngest` against a fake WebSocket server, including drop and reconnect with backoff.
- The buffer route: 200 with correct byte length for a live panel, 404 for an unknown `panel_id` and for a stale `version`.

**End-to-end**
- Launch a `test` deployment config with a `reflex:` entry; assert HTTP 200 on each registered route and a successful backend WebSocket handshake. Run as one file per pytest process, per `run_tests.py`.

**Manual**
- Browser check against the `test` deployment sims: `wssim`, `oersim`, `gpsim`. Confirms rendering, live update, pan/zoom, and selection — the layer automated tests cannot cover, and the only place the hand-written binding is genuinely proven.

## Out of scope

- The operator page (`bokeh_operator.py`, 3076 lines, `orch_backend` coupling, dynamic parameter forms, plate map). Separate spec once this stack is trusted.
- `hte` deployment visualizers. Separate spec; hardware-gated.
- Removing or deprecating any Bokeh code. Decision 1 is coexistence.
- `data_browser` beyond registering its route.
