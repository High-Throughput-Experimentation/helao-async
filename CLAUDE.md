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

A Reflex server occupies **two consecutive ports**: `port` serves the prebuilt static frontend, `port + 1` is the Reflex backend. `validateConfig` reserves both, so nothing else may claim `port + 1`.

Stations never need Node. Build the frontend bundle on a development machine and ship it:

```
conda run -n helao python -c "from helao.core.servers.reflex.xy_component import copy_client_asset; copy_client_asset('helao/core/servers/reflex/_app/assets')"
cd helao/core/servers/reflex/_app && reflex init --name helao_ui --no-agents && reflex export --frontend-only
# then unzip frontend.zip into <repo_root>/.reflex-bundle/helao_ui/   (gitignored)
```

**The build cannot run from a `noexec` filesystem.** `/mnt/STORAGE` is mounted `noexec`, so npm's binaries under `.web/node_modules/.bin/` fail with `Permission denied` (exit 126) no matter what their permission bits say. Stage the `_app` directory somewhere executable (`/tmp` works), build there with `PYTHONPATH` pointed at the repo, and copy the resulting `frontend.zip` back. Only the *build* needs exec — the bundle is static files, and `StaticFiles` serves them from anywhere.

`--name helao_ui` is required: `reflex init` derives the app name from the current directory and rejects `_app`'s leading underscore, ignoring the valid `app_name` already in `rxconfig.py`.

`reflex_launcher.py` serves that bundle and exits non-zero if it is missing, unless `REFLEX_ALLOW_LOCAL_BUILD=1` is set *and* bun/node is on `PATH` — a silent multi-minute build on an instrument PC is worse than a clear error.

Layout and the two rules worth knowing before editing it:

- `helao/core/servers/reflex/` — `app.py` (routes composed from config), `ingest.py`, `ringbuffer.py`, `state.py`, `plots.py`, `xy_component.py`. Panels live in `helao/deploy/<deployment>/servers/reflex/` and are discovered through the same `live_vis:` / `action_vis:` keys the Bokeh visualizers use.
- **The plot facade is used at two call sites.** `plots.chart(spec_var, url_var)` binds a component **once** in a panel's `build()`; `plots.time_series(...)` and friends return a `ChartPayload` **every tick** from `pull()`, which the panel assigns into its state vars. Calling a facade function from `build()` yields a chart that paints once and never updates.
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
