# Framework SP-VIS-1 — Bokeh Visualizer Foundation (design)

**Date:** 2026-06-23
**Branch:** `feat/framework-vis-foundation`
**Cycle:** Operator / data_browser Bokeh UI migration to the new framework (the
"later cycle" deferred in §9 of the core rewrite design,
`2026-06-22-helao-framework-core-rewrite-design.md`).

## 1. Context

The core framework rewrite (`helao/framework/`) deliberately left the Bokeh
presentation layer **out of scope** — see the master design §3 ("Operator/
data_browser UI | Out of scope (own later cycle) | Presentation, not
framework") and §9. This cycle is that later cycle.

The Bokeh presentation layer currently lives in legacy `helao/core/`:

| Component | Legacy location | LOC |
|---|---|---|
| Shared vis foundation | `core/servers/vis.py` (`Vis`/`HelaoVis`) | 91 |
| | `core/servers/vis_subscriber.py` (`VisSubscriber`/`Live`/`Action` + `import_vis_class`/`mount_visualizers`) | 406 |
| data_browser | `core/servers/data_browser/` (app/readers/sources/state) | 768 |
| Operator | `core/servers/operator/bokeh_operator.py` | 2800 |
| | `core/servers/operator/helao_operator.py`, `orch_backend.py` | ~150+ |

The cycle is decomposed into three sub-projects, each with its own
spec → plan → branch:

1. **SP-VIS-1 — Foundation (this spec).** Port the shared vis foundation that
   the other two stand on.
2. **SP-VIS-2 — data_browser.** Self-contained, read-only (reads `RUNS_*` via
   loaders), no orchestrator dependency.
3. **SP-VIS-3 — Operator UI.** Largest; depends on framework `app/orch_api.py`
   endpoints.

Migration depth (decided): **full port into framework layers** — not a compat
shim. The legacy modules keep running untouched for not-yet-migrated
deployments (strangler-fig); this sub-project adds parallel framework modules
and rewires nothing.

## 2. Goal & non-goals

**Goal:** Stand up the shared Bokeh-visualizer foundation in framework layers,
honoring the framework boundary contract, with API parity for the symbols the
rewrite committed to preserve (`Vis`, `HelaoVis`, `LiveVisualizer`,
`ActionVisualizer`, `makeBokehApp`).

**Non-goals (this sub-project):**
- data_browser and operator ports (SP-VIS-2 / SP-VIS-3).
- The server-side `adapters/bokeh_ws.py` eventsink relay. SP8 already added WS
  *publishers* to `app/base_api.py`; the foundation only needs the *subscriber*
  (client) side. A later eventsink-adapter cleanup may extract `bokeh_ws.py`.
- Rewiring any deployment to import the new modules. Deployment cut-over is part
  of SP-VIS-2/3 and the separate deployment-migration cycle.
- Changing the WebSocket wire protocol or `ws_utils.WsSubscriber` internals.

## 3. Boundary contract (from master design §3)

- `domain/` — pure; never imports Bokeh, FastAPI, httpx, filesystem, adapters.
- `adapters/` — implement ports, may import I/O libs (websockets, Bokeh data
  streaming). Never imported by `domain/`.
- `app/` — wiring; composes models + adapters into servers. Bokeh `Document`
  host wiring lives here.

The foundation touches only `app/`, `adapters/`, and `support/`. No `domain/`
code. The AST boundary check must continue to pass (no `domain/` import of
Bokeh).

## 4. Components

### 4.1 `helao/framework/app/vis.py`

Ports `core/servers/vis.py` **and** collapses in the relevant half of
`helpers/server_api.py:HelaoBokehAPI` (the Bokeh path only — no FastAPI/ZMQ
RPC).

- `Vis` — per-server visualization helper: server identity (`MachineModel`),
  `world_cfg` slice, the Bokeh `doc`, resolved `helaodirs`, and
  `print_message`. Raises if `root` is undefined (parity with legacy).
- `HelaoVis` — Bokeh app host: looks up the server config slice from
  `support/config_loader.CONFIG`, initializes the logger if unset, builds
  `MachineModel` (with host/port), sets the document title from
  `params.doc_name`, and constructs a `Vis` onto `self.vis`. Exposes
  `helao_srv`, `helao_cfg`, `server_cfg`, `server_params`, `server`, `doc`,
  `vis` — same attribute surface deployment vis modules read today.
- `makeBokehApp(doc, confPrefix, server_key, helao_repo_root)` — kept for the
  bokeh launcher's import contract (signature unchanged). This module provides a
  minimal generic builder; deployment-specific `makeBokehApp`s (action/live
  visualizers, data_browser shims) continue to live deployment-side and are
  rewired in later sub-projects.

Dependencies: `support/config_loader.CONFIG`, `support/helao_logging`,
`support/helao_dirs.helao_dirs`, `models/machine.MachineModel`. Bokeh imports
(`Document` use via `doc`) are allowed at the app layer.

### 4.2 `helao/framework/adapters/vis_subscriber.py`

Ports `core/servers/vis_subscriber.py` near-verbatim. This is an I/O adapter:
it owns a WebSocket client and streams batches into Bokeh `ColumnDataSource`s
on the document thread.

- `VisSubscriber` — bring-up base: resolve target action server from
  `world_cfg`, open a `WsSubscriber` on `WS_PATH`, the `max_points`/
  `update_rate` input callbacks (with clamping), `_mount`, `cleanup_session`,
  and the `IOloop_data` ingest loop scheduling `add_points` via
  `doc.add_next_tick_callback`. `add_points` stays abstract.
- `LiveVisualizer` (`ws_live`, guards empty messages) and `ActionVisualizer`
  (`ws_data`, fast cadence) specializations — unchanged semantics.
- `import_vis_class(module_name, class_name="C_vis")` and
  `mount_visualizers(app, vis_cfg_key)` — deployment `C_vis` discovery/mount
  helpers. Kept here (per master design §3 adapters list). They scan
  `helao/deploy/<deployment>/servers/visualizer/` in
  `CONFIG["deployment"]`-first order, exactly as today.

Dependencies: `helao/framework/app/vis.py:Vis` (type only),
`helpers/ws_utils.WsSubscriber` (reused as-is for now),
`support/config_loader.CONFIG`, Bokeh layout primitives.

> **Note — temporary cross-package import.** `vis_subscriber` reuses the legacy
> `helpers/ws_utils.WsSubscriber` rather than porting it. This is an
> intentional strangler-fig seam; porting/replacing the ws client (possibly
> through the `transport` port) is deferred. The import is from `helpers/`, not
> `core/`, and does not cross the domain boundary.

### 4.3 `helao/framework/support/helao_dirs.py`

Port `helpers/helao_dirs.py` (`helao_dirs()` + `HelaoDirs`) — builds the
standard HELAO directory tree (`RUNS_*`, `LOGS`, etc.) and returns a
`HelaoDirs`. Required by `Vis.__init__`. Port near-verbatim; it is pure
filesystem-layout utility code appropriate for `support/`.

## 5. Data flow

```
bokeh launcher → makeBokehApp(doc, ...) [app/vis.py]
                   └─ HelaoVis(server_key, doc)         # host + identity + dirs
                        └─ Vis(self)                     # doc, helaodirs, logger
                   └─ mount_visualizers(app, key)        [adapters/vis_subscriber]
                        └─ import_vis_class(module)       # deployment C_vis
                        └─ C_vis(vis_serv=app.vis, ...)   # VisSubscriber subclass
                             └─ WsSubscriber(host,port,path)  ── ws ──▶ action server
                             └─ IOloop_data → add_points → ColumnDataSource (doc thread)
```

No new network protocol; the subscriber connects to the same action-server WS
endpoints (`ws_live`/`ws_data`) the SP8 `base_api.py` publishers serve.

## 6. Error handling (parity)

- `Vis` raises `ValueError` when `helaodirs.root` is `None` (matches legacy).
- `VisSubscriber.__init__` returns early with `connected=False` when the target
  server key is absent from the config; subclasses must likewise return without
  mounting roots (documented contract, unchanged).
- `import_vis_class` raises `ModuleNotFoundError` listing the tried module paths
  when no deployment provides the module; a module that exists but fails to
  import surfaces its real error (uses `find_spec` to probe).
- Input callbacks clamp `max_points` to `[2, 10000]` and fall back to defaults
  on bad input.

## 7. Test strategy

No Bokeh-server test harness exists in the repo. Strategy: **unit tests with a
fake Bokeh `Document` and a fake WS source** (decided), plus the existing AST
boundary check.

New tests under `helao/framework/tests/`:

- `test_app_vis.py`
  - `HelaoVis` builds against a minimal `CONFIG` slice: title set from
    `params.doc_name`, `server`/`server_cfg`/`server_params` populated, `vis`
    is a `Vis`.
  - `Vis` raises `ValueError` when `root` is undefined.
  - `makeBokehApp` returns the passed `doc` with expected roots added (use a
    fake/recording `Document` capturing `add_root`).
- `test_adapters_vis_subscriber.py`
  - `VisSubscriber` resolves a configured server → `connected=True`; absent
    server → `connected=False`, no roots.
  - `_mount` adds the layout root (+ spacer) and registers a session-destroyed
    cleanup; `cleanup_session` cancels the ingest task.
  - `callback_input_max_points` clamps `[2,10000]` and recovers from bad input;
    `callback_input_update_rate` parses float / falls back to 0.5.
  - `IOloop_data` drains a fake ws source and schedules `add_points` (drive one
    iteration with a fake `WsSubscriber.read_messages`); `GUARD_EMPTY_MESSAGES`
    respected for `LiveVisualizer` vs `ActionVisualizer`.
  - `import_vis_class` resolves a temp deployment module and raises
    `ModuleNotFoundError` (with tried paths) when absent.
  - `mount_visualizers` honors `limit_vis` and string-vs-list `vis_cfg` values.
- `test_support_helao_dirs.py`
  - `helao_dirs` builds the directory tree under a temp root and returns a
    populated `HelaoDirs`; all-`None` paths when root undefined.

Fakes: a `FakeDoc` recording `add_root`/`add_next_tick_callback`/
`on_session_destroyed`/`title`, and a `FakeWss` with a scriptable
`read_messages`. Prefer running under the `helao` conda env (Python 3.12).

The AST boundary check must still pass: `domain/` imports no Bokeh; the new
adapter's Bokeh + `helpers/ws_utils` imports are permitted at the adapter layer.

## 8. API parity (must-preserve symbols)

From master design §6 "most-depended-on symbols to preserve":
`Vis`, `HelaoVis`, `LiveVisualizer`, `ActionVisualizer`, and the
`makeBokehApp` factory. Public attribute surfaces of `HelaoVis`/`Vis`/
`VisSubscriber` are preserved so deployment `C_vis` modules can be repointed to
the framework modules in later sub-projects with import-path changes only.

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Bokeh behavior drift vs legacy | API-parity attribute surface + unit tests against fake doc; legacy modules remain untouched until deployment cut-over |
| Temporary `helpers/ws_utils` coupling reads as a boundary leak | Documented seam (§4.2); import is `helpers/`, not `core/`, and not from `domain/` |
| `helao_dirs` port diverges from legacy | Port near-verbatim; unit test the tree build |
| Scope creep into data_browser/operator | Hard non-goals (§2); deployment rewiring explicitly deferred |

## 10. Done criteria

- `app/vis.py`, `adapters/vis_subscriber.py`, `support/helao_dirs.py` exist with
  parity APIs.
- New unit tests pass under the `helao` env; full framework test suite still
  green; AST boundary check still green.
- No deployment or legacy `core/` module modified (pure addition).
- Spec committed; ready to hand SP-VIS-2 (data_browser) the foundation.
