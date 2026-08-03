# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

HELAO-async is Caltech HTE group's instrument control software following [HELAO](https://doi.org/10.26434/chemrxiv-2021-kr87t) design principles: a distributed system of cooperating FastAPI and Bokeh servers (action drivers, orchestrators, visualizers, operator UIs) launched together as a configurable "orchestration group". As of release 2025.07.07 the former `helao-core` package was merged in-tree under `helao/core/`, so this repo is self-contained.

Development happens on `unstable`; only stable releases land on `main`.

## Environment & common commands

The codebase runs inside a conda env named `helao` (Python 3.14, pinned by `helao_dev_linux-64.yml` / `helao_dev_win-64.yml`), and `PYTHONPATH` must point at the repo root. The setup script sets this in the conda env config.

```
bash setup_env.sh                   # (Linux) create+configure 'helao' env
setup_env.bat                       # (Windows)
```

Launching an orchestration group (matches the prefix of a YAML in `helao/deploy/*/configs/`):

```
./helao.sh <config_prefix>          # Linux wrapper
helao.bat <config_prefix>           # Windows wrapper
python launch.py <config_prefix> [extraopt] [--restore] [--hot-reload | --no-hot-reload]
```

`extraopt` values understood by `launch.py`: `liveonly`/`gpvis` (only the live_visualizer Bokeh app), `nolive`/`actionvis` (suppress live_visualizer). Hotkeys after launch: `CTRL-r` restart a single server, `CTRL-x` terminate the group, `CTRL-t` toggle the hot-reload watcher on/off at runtime, `CTRL-d` disconnect monitor.

CLI flags (position-independent; parsed separately from `extraopt`):
- `--restore` — launched orchestrators import their previously exported queues (`STATES/queues.pck`) on startup. Per-instrument persistent equivalent: `restore_queues_on_startup: true` on the orchestrator's server config. A restored `queues.pck` is archived (`queues_imported_<ts>.pck`) so it is not replayed again.
- `--hot-reload` / `--no-hot-reload` — the hot-reload watcher (watches the parent repo and each nested `helao/deploy/*` git repo; on a pulled commit, restarts idle servers whose loaded code changed) runs **on by default**. Disable with `--no-hot-reload` or `hot_reload.enabled: false` in the config; `hot_reload.poll_seconds` (default 30) tunes the poll interval. Precedence: `--no-hot-reload` > `--hot-reload` > config. Affected servers are mapped via each server's `/loaded_modules` endpoint (bokeh servers use a `STATES/loaded_modules_<key>.json` startup snapshot); orchestrators are only reloaded when idle and restart with `--restore`.

Other utilities:
- `python run_unit_tests.py` — runs `helao.core.tests.unit_test_sample_models.sample_model_unit_test`. `launch.py` runs this automatically before launching anything and aborts on failure.
- `python run_tests.py` — the full pytest sweep across this repo and every deployment (`--list` to preview, `--filter <substr>` to narrow, `--timeout` to raise the per-file cap). **Runs one file per pytest process**, because collecting the tree as a single session hangs indefinitely and ignores SIGINT while the same files pass individually — the tests start event loops, bind sockets, and spawn Bokeh servers, so cross-file interference is expected. Deliberately separate from `run_unit_tests.py`, which stays a fast pre-launch gate. Deployments opt in by having a `tests/` directory; the whole deployment is then swept for `test_*.py`, so a test filed beside its subject is not missed. Third-party import failures report as `ENV` rather than `FAIL` (a Windows-only vendor SDK cannot be collected on Linux), while a missing `helao*` module stays a failure.
- `python -m helao.core.tests.check_queue_pcks <STATES dir>` — read-only report of which `queues*.pck` files the current build could actually restore (missing model classes, or a payload schema this build does not write). Never loads a pickle; walks the opcode stream instead. Exits 1 if any file is unrestorable, so it can gate a cleanup sweep.

There is no project-wide build step for the Python side. Tests are a mix of pytest modules (most of `helao/hexagon/tests/`, `harness/tests/`, and each deployment's `tests/`) and standalone `__main__` scripts under `helao/core/tests/` that `run_tests.py` reports as `NOTESTS` and which must be invoked directly.

### Reflex UI stack (coexists with Bokeh)

An optional second UI stack, opt-in per config via a `reflex:` server key alongside `fast:`/`bokeh:`. The Bokeh path is untouched; a station runs either, or both in the same group. Try it with `python launch.py goldenreflex`.

A Reflex server occupies **two consecutive ports**: `port` serves the prebuilt static frontend, `port + 1` is the Reflex backend. `validateConfig` reserves both, so nothing else may claim `port + 1`. The frontend server proxies `/xy/buffers/*` through to the backend, because the chart-buffer route is registered on the backend while the browser resolves the payload's relative URL against the page origin.

Stations never need Node. Build the frontend bundle on a development machine and ship it:

```
python build_reflex_bundle.py <config_prefix_or_path> [--server KEY]
```

`build_reflex_bundle.py` does the whole sequence: reads the config's Reflex
server, bakes that server's backend URL in, stages the build off a `noexec`
filesystem when it has to, and only replaces the installed bundle once the
export has actually produced one. It needs `bun` or `node` on `PATH`, which is
why `nodejs` is in the *development* environment files and not the station
ones.

**The build cannot run from a `noexec` filesystem.** `/mnt/STORAGE` is mounted `noexec`, so npm's binaries under `.web/node_modules/.bin/` fail with `Permission denied` (exit 126) no matter what their permission bits say. Stage the `_app` directory somewhere executable (`/tmp` works), build there with `PYTHONPATH` pointed at the repo, and copy the resulting `frontend.zip` back. Only the *build* needs exec — the bundle is static files, and `StaticFiles` serves them from anywhere.

**The exported bundle bakes the backend URL**, from `HELAO_REFLEX_API_URL` (default `http://127.0.0.1:5011`). A bundle built for one config's port serves a *blank, silently disconnected* page under a config on any other port — the panels render and then every WebSocket attempt is refused. Export with the port the target config uses:

```
HELAO_REFLEX_API_URL=http://127.0.0.1:<port+1> reflex export --frontend-only
```

`--name helao_ui` is required: `reflex init` derives the app name from the current directory and rejects `_app`'s leading underscore, ignoring the valid `app_name` already in `rxconfig.py`.

`reflex_launcher.py` serves that bundle and exits non-zero if it is missing, unless `REFLEX_ALLOW_LOCAL_BUILD=1` is set *and* bun/node is on `PATH` — a silent multi-minute build on an instrument PC is worse than a clear error.

Layout and the two rules worth knowing before editing it:

- `helao/core/servers/reflex/` — `app.py` (routes composed from config), `ingest.py`, `ringbuffer.py`, `state.py`, `plots.py`, `xy_component.py`. Panels live in `helao/deploy/<deployment>/servers/reflex/` and are discovered through the same `live_vis:` / `action_vis:` keys the Bokeh visualizers use.
- **The plot facade is used at two call sites.** `plots.chart(spec_var, url_var, layout_var)` binds a component **once** in a panel's `build()`; `plots.time_series(...)` and friends return a `ChartPayload` **every tick** from `pull()`, which the panel assigns into its state vars. Calling a facade function from `build()` yields a chart that paints once and never updates.
- **Panel state bases are Reflex mixins, and must stay that way.** A var declared on a concrete `rx.State` is owned by that class and *shared* by every substate under it; a subclass re-declaring it does not shadow it. Written as plain inheritance, `make_panel_state`'s `server_key` binding read back as `""` at runtime and every panel on a page shared one `chart_spec`. `make_panel_state` raises if handed a non-mixin base.
- **`add_page` takes a lazy callable that `--backend-only` never runs.** Anything the serving process needs — above all the panel state classes, since Reflex registers event handlers at class creation — must be created *before* `add_page`, or the browser calls handlers the backend has never heard of and every panel sits at "connecting".
- **The data browser has two UIs over one logic layer.** `helao/core/servers/data_browser/{readers,state,sources}.py` are backend-agnostic and shared; `app.py` is the Bokeh document and `app_reflex.py` is the Reflex page on `/browser`. Never fork behaviour into one UI — add it to the shared layer so the other keeps working.
- **The operator likewise has two UIs over one `OrchBackend`.** `orch_backend.py` is the async ABC both consume; `bokeh_operator.py` is the Bokeh document (named by 32 configs, still the production UI) and `operator/app_reflex.py` is the Reflex page on `/operator`. Three shared layers sit under both — `param_forms.py` (library introspection, `Args:` parsing, version hints, `BUILTIN_TYPES`), `param_store.py` (`previous_params.json`, which one UI may write and the other read), and `spec_parser.py` (loading a deployment's `SpecParser` and parsing spec files). Add to those rather than to one UI. `test_standalone_operator.py`'s 48 tests are the gate on any change to them: they must pass with `bokeh_operator.py` unedited.
- **A deployment's spec parser is code this repo never sees.** `spec_parser.load_parser` executes a file named by `seqspec_parser_path`, so every function in that module degrades to "nothing configured" instead of raising — a broken parser disables the Specs tab rather than taking down the page. The contract is `SpecParser` with `.lister`, `.PARAM_TYPES`, `.list_params`, and `.parser`.
- **The Reflex process runs from `_app/`, not the repo root.** `import_autolibs` resolves every library path relative to the cwd, so a config's `helao/deploy/<dep>/experiments` silently yields an *empty* library plus one ERROR line — the operator then renders with nothing to select. `operator/app_reflex.rooted_config` rewrites those paths against the repo root before handing the config to `RemoteBackend`. Anything else in a Reflex process that resolves a config path relative to the cwd has the same bug.
- **A checkbox's value is not a string.** `str(False)` is `"False"` and `bool("False")` is `True`, so routing a checkbox through the same coercion as a text field inverts every unchecked box. The operator has a separate handler and reader for bool fields.
- **Never drive a refresh from a server-side `while True`.** `on_unmount` fires on in-app navigation but *not* on tab close, so a `background=True` loop keeps running after the browser is gone — polling the orchestrator forever and logging `Attempting to send delta to disconnected client`. Both the operator and the visualizer panels tick from a `rx.moment(interval=..., on_change=...)` in the page instead: a component stops existing when its tab does. The panel tick is added by `app._render_panel`, not by panel modules, so panels in deployments outside this repo need no change; `VisPanelState.render_loop` is kept as the mount primer they already bind.
- **Reflex vars that `rx.foreach` iterates need element annotations.** A bare `list` fails the *frontend build* with `ForeachVarError`, not at import, so it looks fine until `reflex export` runs. Use `list[list[str]]`, not `list`.
- **hte panels resolve by the same config key as the Bokeh visualizers.** `helao/deploy/hte/servers/reflex/co2_vis.py` answers to the same `live_vis: co2_vis` that `servers/visualizer/co2_vis.py` does — different subpackages, one name. A station gains the Reflex panels by adding a `reflex:` server and changing nothing else. `htereflex.yml` is a development config for verifying them without hardware and is not a station config.
- **Every chart is a WebGL context, and the browser caps how many are live.** Chrome allows 16 and evicts the oldest past that, warning `Too many active WebGL contexts. Oldest context will be lost`. An evicted chart stops drawing *permanently* while every other signal still reads healthy — data arrives, the view is mounted, the append fires, and xy's `_applyAppend` returns at its `_glLost` guard before touching the GPU. Nothing is logged server-side. Budget charts per page accordingly: the hte action page was at 10 (16 with four BioLogic channels) until the per-action figures were merged into one chart carrying both segments as traces (`_action.segment_traces`). A panel that wants "this" beside "previous" should add a trace, not a chart.
- **Not every HELAO data column is numeric.** Datasets carry an orchestrator host or a status message beside the traces; handing one to `plots` raises `could not convert string to float` from inside the render and takes down the whole chart. Filter columns before plotting.
- **`ws_live` and `ws_data` carry different payloads.** `ws_live` relays a `{datalab: (value, epoch)}` dict; `ws_data` carries a pickled `DataPackageModel` object whose samples sit at `.datamodel.data[key][column]`. `ingest.NORMALIZERS` selects the right one by `ws_path` — a single normalizer silently drops the other endpoint's messages with no error.

Only `plots.py` and `xy_component.py` may import `xy` (a test enforces this). `xy` is pre-1.0; `docs/superpowers/notes/2026-08-01-xy-api-probe.md` records its verified call signatures and should be re-checked after any version bump.

### Formatting

`black` (default settings, line length 88) is the project code formatter.

**Rule: always run `black` on the changed files as the final step before every commit** — after all edits are complete and verification has passed, immediately prior to `git add`/`git commit`. This applies to the parent repo and each nested deployment repo independently (format and commit within the repo that owns the files).

```
black <changed_files>          # run inside the `helao` conda env, right before committing
```

There is no separate linter config; `ty` (Astral type checker) may be used as a stricter secondary pass over the pyright default (`ty.toml` pins Python 3.14), but `pyright` (`pyrightconfig.json`, basic mode) remains the authoritative type checker — do not remove `# type: ignore` directives that pyright needs.

## Architecture

### Three-layer layout
- `helao/core/` — framework that doesn't depend on a specific instrument deployment: base FastAPI/Bokeh server classes (`servers/base.py`, `servers/base_api.py`, `servers/orch.py`, `servers/vis.py`), pydantic models for `Action`/`Experiment`/`Sequence`/`Sample`/etc. (`models/`), the abstract driver contract (`drivers/helao_driver.py` — `HelaoDriver`, `DriverPoller`, `DriverResponse`, `DriverStatus`), the data syncer (`drivers/data/sync_driver.py`), and the in-process "micro-orchestrator" runners (`runners/`, see `runners/runner.md`).
- `helao/deploy/<deployment>/` — one directory per physical/simulated instrument family. Each has the same shape: `configs/` (YAMLs that define a server group), `servers/{action,orchestrator,visualizer,operator}/` (FastAPI apps via `makeApp(server_key)` or Bokeh apps via `makeBokehApp(...)`), `drivers/` (hardware backends — many vendor-specific), `experiments/` and `sequences/` (the action/experiment/sequence library code referenced by configs), plus `specifications/`, `processors/`, `tests/`, `layouts/` as needed. Known deployments: `hte` (production HTE stations), `test` (sims and demos). Only `hte` and `test` are tracked in this repo; `.gitignore` excludes all other `helao/deploy/*` directories, which are **separate git repositories** nested in-tree. To commit changes under those, `cd` into the deployment directory (`helao/deploy/<deployment>`) and use its own git — they have their own branches/remotes and are invisible to the parent repo's `git status`. Never name those deployments in tracked parent-repo files: this repo is a public remote, so refer to them as "private deployments".
- `helao/helpers/` — cross-cutting utilities: `config_loader.py` (resolves a prefix to a YAML/Py config and exposes the global `CONFIG`), `helao_logging.py` (logger factory used by every server), `dispatcher.py` (async HTTP RPC between servers), `premodels.py` (`Action`, `Experiment`, `Sequence`), plus YAML/HLO/parquet/zip/zeromq helpers.

### Launch flow
1. `launch.py` parses `<config_prefix>`, calls `read_config()` to find `helao/deploy/*/configs/<prefix>.yml`, validates the `servers:` block (unique keys, unique `host:port`, one of `fast`/`bokeh` per entry), then iterates `LAUNCH_ORDER = ["action", "orchestrator", "visualizer", "operator"]`.
2. For each server it shells out to either `fast_launcher.py` (uvicorn) or `bokeh_launcher.py` (Bokeh `Server`), passing the same config prefix and the server key.
3. The launcher dynamically imports `helao.deploy.<deployment>.servers.<group>.<fast|bokeh>` and calls `makeApp(server_key)` or `makeBokehApp(...)`. **Deployment is normally auto-detected** from where the config file lives (`helao/deploy/<deployment>/configs/...`), but a per-server `deployment:` key in the config overrides this, and when the same `<group>/<fast>.py` exists in multiple deployments the launcher disambiguates by preferring the deployment matching the config path.
4. PIDs of spawned processes are pickled to `<root>/STATES/pids_<prefix>_<extraopt>.pck`. The launcher tracks them with `psutil` and uses POST `/shutdown` (FastAPI) plus `psutil` termination on exit.

### Server roles inside a group
- **action servers** (`group: action`, code under `servers/action/`) — wrap a specific driver and expose `/<server_key>/<action>` POST endpoints. They build on `helao.core.servers.base_api.BaseAPI`, which wires in the `Base` class from `core/servers/base.py` (status WS, action lifecycle, hlo file output, NTP-synced clock, etc.).
- **orchestrator servers** (`group: orchestrator`, usually `async_orch2.py`) — extend `Base` via `core/servers/orch.py`'s `Orch`. They own the sequence/experiment/action deques, dispatch actions to action servers over HTTP, react to status updates, and can host a Bokeh "operator" page (`enable_op: true`, `bokeh_port: <port>`).
- **visualizer servers** (`group: visualizer`, `bokeh: ...`) — Bokeh apps that subscribe to action server status/data WebSockets and render plots.
- **operator servers** (`group: operator`) — separately launched UIs (e.g. `gcld_operator.py`) or post-run processors.

Action servers, experiments, and sequences are written as importable Python; the `experiment_libraries:` / `sequence_libraries:` lists in the config name modules under `helao/deploy/<deployment>/{experiments,sequences}/` that the orchestrator dynamically imports.

### Data and state on disk
Server output is rooted at the YAML's `root:` key (e.g. `C:\INST_hlo`):
- `LOGS/<server_name>/` — rotating text logs; `launch.py` zips old `*.txt` logs at startup using a timestamp parsed from the first log line.
- `STATES/` — pickled PID files and other runtime state.
- `RUNS_*` — per-run output trees consumed by `HelaoSyncer` (e.g. `RUNS_SYNCED` is the canonical "shipped" location; recent commits in `git log` show ongoing churn around this name).

### Two execution models: Orchestrator vs Runners
The orchestrator is the long-lived queue-and-dispatch service used in production. `helao/core/runners/` provides an alternative "micro-orchestrator" pattern (`action_runner`, `experiment_runner`, `sequence_runner`, `micro_client`) for callers that want a short-lived runner with no backend service. See `helao/core/runners/runner.md`. Several of those files are currently stubs.

## Conventions worth knowing
- Drivers must implement the `HelaoDriver` ABC (`connect`/`get_status`/`stop`/`reset`/`disconnect`) and return `DriverResponse` objects; pollers extend `DriverPoller` with `get_data`.
- Action server modules expose a `makeApp(server_key) -> HelaoFastAPI` factory; Bokeh modules expose `makeBokehApp(...)`. The launchers find these by import path, so module/file names in `servers/<group>/` must match the `fast:` / `bokeh:` value in the config.
- Configs may be `.yml` (loaded via `yml_load`) or `.py` (which must define a top-level `config` dict). `read_config` accepts either a full path or a bare prefix and globs `helao/deploy/*/configs/<prefix>.*`.
- The `dummy: true` / `simulation: true` keys at the top of a config govern banner color and whether simulated drivers are used.
- Logging: do not instantiate loggers directly; use `helao.helpers.helao_logging.make_logger(__file__)` (or the already-initialized `logging.LOGGER`) so per-server log routing and email alerts work.
- Windows-only drivers: Galil (`gclib`) and Gamry (`comtypes`). Most other code, and the `test` deployment's simulators, run on Linux.
