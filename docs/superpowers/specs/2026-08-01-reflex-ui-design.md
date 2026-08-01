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

`xy` (`reflex-dev/xy`) is a Rust/WebGL2 charting library with a native Reflex adapter. It ships line, scatter (with density surfaces), and polar charts today; the roadmap covers the rest. It is **pre-1.0 alpha** and its own documentation states that "callback payloads, the Reflex adapter, chart breadth ... may change." Its Reflex-integration docs page is currently empty. This risk is mitigated by the plot facade (below), not by avoiding xy.

One honest caveat on performance: today's live visualizers cap at `max_points` 10000 (`vis_subscriber.py`), default 500. Bokeh is not slow at 10k points, so xy's large-dataset advantage does not by itself explain live-plot stutter. The stutter is addressed architecturally by decoupling ingest rate from render rate; xy's advantage lands on `spec_vis`, plate maps, `data_browser`, and on raising the buffer depth far past 10k.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **Coexist indefinitely** with Bokeh | Additive. The Bokeh path is untouched; stations opt in per config. No forced cutover, no production blast radius. |
| 2 | **One Reflex app, multi-page routes** per orchestration group | One process, one port, one frontend build. Running one Reflex app per config entry would mean 4 Next.js builds and 4 processes per station. |
| 3 | **Process-wide ingest with ring buffers** | One WebSocket per action server for the whole process instead of N sessions × M servers. Decouples ingest rate from render rate. |
| 4 | **Thin plot facade over xy** | xy is alpha. All charts call a small HELAO API; xy sits behind it, version-pinned. An adapter break touches one file, not 14. |
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

## Plot facade

`helao/core/servers/reflex/plots.py` is the only module that imports `xy`. Three functions cover all existing visualizers:

| Function | Covers |
|---|---|
| `time_series(buf, x, ys, **opts)` | co2, mfc, temp, pressure, tec, power_supply, syringe, nidaqmx, gamry, biologic, gpsim, wssim |
| `spectra(buf, **opts)` | spec_vis |
| `scatter_map(points, on_select=..., **opts)` | sample_vis, the operator plate map, oersim |

Each returns an `rx.Component`. The xy version is pinned in `helao_dev_linux-64.yml` and `helao_dev_win-64.yml`. Swapping the plotting backend means editing this one file.

Tables use native `rx.data_table`; xy is not involved in tabular display.

## State model

`LiveVisState` and `ActionVisState` are the Reflex analogues of `LiveVisualizer` and `ActionVisualizer`. They carry `max_points`, `update_rate`, the render loop, and connection status. A per-instrument module subclasses one of them and supplies the data-specific column transform — the direct analogue of today's `add_points`.

## Error handling

| Condition | Behavior | Change from today |
|---|---|---|
| Target server absent from config | Panel renders a disabled placeholder stating the missing server key | Today: silent early return via `self.connected = False`, blank page |
| WebSocket drop | Ingest retries with backoff; panel shows a "reconnecting" badge | Today: no reconnect, feed dies silently |
| xy import or API failure | Facade raises at import; launcher logs and refuses to start | Prevents serving half-rendered pages |
| Ring buffer overflow | Oldest rows dropped | By design |
| Prebuilt bundle missing and no Node | Launcher fails with an explicit error naming the expected bundle path | New failure mode, made loud |

## Testing

**Unit**
- `RingBuffer` append / snapshot / rollover — pure numpy, no IO.
- `launch.py` validation: exactly one of `fast:` / `bokeh:` / `reflex:`; duplicate `host:port` still rejected.
- Config → route list and panel composition.
- Plot facade returns a component for each of the three functions against synthetic data.

**Integration**
- `WsIngest` against a fake WebSocket server, including drop and reconnect with backoff.

**End-to-end**
- Launch a `test` deployment config with a `reflex:` entry; assert HTTP 200 on each registered route and a successful backend WebSocket handshake. Run as one file per pytest process, per `run_tests.py`.

**Manual**
- Browser check against the `test` deployment sims: `gpsim_live_vis`, `oersim_vis`, `wssim_live_vis`. Confirms rendering, pan/zoom, and plate-map selection — the one layer automated tests cannot cover.

## Out of scope

- The operator page (`bokeh_operator.py`, 3076 lines, `orch_backend` coupling, dynamic parameter forms, plate map). Separate spec once this stack is trusted.
- `hte` deployment visualizers. Separate spec; hardware-gated.
- Removing or deprecating any Bokeh code. Decision 1 is coexistence.
- `data_browser` beyond registering its route.
