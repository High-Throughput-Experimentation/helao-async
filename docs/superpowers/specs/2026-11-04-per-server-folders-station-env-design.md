# Per-server folders and station-aware environment setup

Date: 2026-11-04
Status: approved design, pending implementation plan

## Goal

Group each instrument's code and external dependencies in one folder, and make
`setup_env` / `update_env` install only the dependencies of the servers a station
actually runs. The framework (`helao/core`, `helao/hexagon`, `helao/helpers`,
`helao/ui`, launchers) stops importing or naming any hardware deployment.

Non-goals:

- No repository split. Hardware code stays in its deployment (`hte` in this repo,
  private deployments in their own nested repos). Private hardware code never
  enters this public repo.
- No config-file changes. Every `fast:`, `bokeh:`, `reflex:`, `action_vis:`,
  `live_vis:` and `deployment:` value keeps working.
- No uninstall. Dropping a config from a station does not remove packages.

## Background

- `helao/deploy/hte` holds 80 driver files in 13 categories, 24 action servers,
  22 Bokeh visualizers and 22 Reflex panels. Driver to action server is almost 1:1:
  each server imports its own `...drivers.<category>.<x>` package (BioLogic's three
  backends all feed `biologic_server`).
- The generic UI (`helao/ui/{bokeh,reflex,shared}`) imports no deployment code.
- The framework still couples to `hte`:
  - hexagon hardware adapters: `adapters/native/galil_motion_native.py`,
    `adapters/native/gamry_com.py`, `adapters/vis/galil_aligner_host.py`, plus the
    Galil command channel, PAL trigger and NI adapters;
  - 53 core/hexagon tests import `helao.deploy.hte`;
  - hardcoded `hte` fallbacks in `ui/shared/discovery.py`, `core/hooks/loader.py`,
    `helpers/import_autolibs.py`, `hexagon/preflight.py`, `harness/hte_freeze.py`.
- Hardware Python dependencies (pyserial, pyvisa, pylablib, pymodbus, pyftdi,
  pyusb, nidaqmx, pyft232, pyMeCom, comtypes) sit in the shared base env
  (`helao_dev_<os>.yml`, `requirements.txt`). Vendor SDKs (gclib, BioLogic EClib,
  Andor) are installed by hand.

## Design

### 1. Per-instrument server folders

Every deployment (`hte`, `test`, private) uses the same layout:

```
helao/deploy/<dep>/servers/
  gamry/                      # one instrument = one importable package
    __init__.py
    gamry_server2.py          # makeApp; filename unchanged (config: fast: gamry_server2)
    driver.py, technique.py, signal.py, readz.py   # was drivers/pstat/gamry/*
    bokeh/gamry_vis.py        # Bokeh visualizer; filename unchanged
    reflex/gamry_vis.py       # Reflex panel; same name on purpose (see Rules)
    environment.yml           # optional: conda deps
    requirements.txt          # optional: pip deps
    README.md                 # optional: vendor SDK install notes
    tests/                    # optional: device tests
  orchestrator/ operator/ visualizer/ reflex/   # multi-device / generic servers stay
```

Rules:

- Module filenames do not change, so config values do not change.
- Folder names are valid Python identifiers.
- A config key such as `action_vis: gamry_vis` loads the Bokeh module in a Bokeh
  group and the Reflex module of the same name in a Reflex group (15 such twins in
  `hte`). Twins therefore live in the instrument's `bokeh/` and `reflex/` subfolders.
  A Bokeh visualizer is found only at `servers/visualizer/<m>.py` or
  `servers/*/bokeh/<m>.py`; a Reflex panel only at `servers/reflex/<m>.py` or
  `servers/*/reflex/<m>.py`; a `fast:`/`bokeh:` app module only at
  `servers/*/<m>.py` outside `servers/reflex/`.
- Multi-device or generic UIs stay in their group folders: `live_visualizer`,
  `action_visualizer`, `control_visualizer`, `data_browser`, operator, orchestrator,
  the shape-generic panels used by several instruments or deployments
  (`motion_control_*_scale`, `digital_out_control`, `temp_vis`, `pressure_vis`) and
  the `_`-prefixed helpers (`_live_panel`, `_vis_host`, `_pstat`, `_spectra`, ...).
- Code shared by several instruments or imported by experiments goes to its main
  owner's folder; the other users import across folders.

Moves in `hte`:

| From | To |
|---|---|
| `drivers/<category>/<x>` | the server folder that uses it; a single-directory driver moves flat, a multi-package driver (BioLogic) keeps its subpackages |
| `drivers/pstat/biologic*`, `biologic_backend.py` | `servers/biologic/` |
| `drivers/io/enum.py` | `servers/galil_io/` (also used by spec and 7 experiments) |
| `drivers/motion/enum.py` | `servers/galil_motion/` (also used by the aligner layout and 6 experiments) |
| `drivers/spec/enum.py` | `servers/spec/` |
| `drivers/robot/pal_driver.py` | `servers/pal/` (also used by 2 experiments) |
| `drivers/serial_lifecycle.py` | `helao/helpers/serial_lifecycle.py` (generic) |
| `drivers/data/*` (calc, archive, HTEdata_legacy) | their server folders, no env files |
| `drivers/data/analyses/` | `servers/analysis/analyses/`; `analysis_driver` tries `servers.analysis.analyses` then the old `drivers.data.analyses`, so private deployments keep working until they move |
| `drivers/test_station/leancat/` | stays where it is (nothing imports it) |
| hexagon Galil motion adapter, Galil command channel (adapter + port), aligner host | `servers/galil_motion/` |
| hexagon `gamry_com` | `servers/gamry/` |
| hexagon PAL transport and trigger (adapters + ports), `domain/pal_reconciliation.py`, the PAL models in `domain/models.py` | `servers/pal/` |
| hexagon `calibration_store`, `domain/motion_transform.py` | stay (pure, used by private deployments) |
| hte-importing core/hexagon/harness tests and helpers | matching server folder `tests/` or `hte/tests/` |
| `harness/hte_freeze.py`, `hexagon/tests/checklists/hte/` | checklists to `hte/tests/checklists/` (already preferred by `preflight._checklist_dir`), frozen by the generic `harness/freeze.py`; `hte_freeze.py` deleted |

The aligner host has one private consumer, so that deployment's import fix merges
together with P2. There is no compatibility shim.

`hexagon/adapters/native/native_syncer.py` and `sync_adapter.py` are not hardware and
stay in hexagon.

### 2. Module resolution

One resolver module, `helao/helpers/server_modules.py`, finds a module by the
per-stack globs in section 1 (app, Bokeh, Reflex) under `helao/deploy/<dep>/servers/`.

- Deployment order is unchanged: explicit `deployment:` key, then the config's own
  deployment, then the one other deployment that has the module. The hardcoded
  `hte` fallback is removed everywhere (launchers, panel discovery, processors,
  experiment/sequence libraries, preflight).
- A module found in several other deployments, none of them the config's own, is
  reported with every candidate. The launcher keeps today's behaviour there (warn,
  take the first in sorted order); panel, processor and library lookups, which used
  to prefer `hte`, raise instead. Before this lands, a check lists every name found
  in more than one deployment on the machine; any collision a config relies on is
  resolved first.
- A config outside `helao/deploy/*/configs/` still needs an explicit `deployment:`
  key, as today.
- Two files with the same module name inside one deployment is a hard error that
  names both paths.
- The old layout (`servers/action/x.py`) already matches `servers/*/x.py`, so the
  resolver works before and after the reorganization.

Callers switched to the resolver: `fast_launcher.py`, `bokeh_launcher.py`,
`reflex_launcher.py`, `launcher_bootstrap.resolve_app_deployment`,
`ui/shared/discovery.py`, `ui/bokeh/vis_subscriber.py`,
`core/drivers/data/analysis_driver.py`, `core/hooks/loader.py`,
`helpers/import_autolibs.py`.

The Reflex bundle stamp and the hot-reload watcher already scope to `helao/` and the
nested deploy repos; folder moves inside a deployment need no change there. Verify
this in P2 rather than assume it.

### 3. Station-aware environment setup

The `.sh` and `.bat` wrappers keep their base-env steps (create/update the `helao`
env from `helao_dev_<os>.yml`, `uv pip install -r requirements.txt`, set
`PYTHONPATH` and `HELAOLAUNCH`). They then call one shared script, `helao_env.py`,
so the logic exists once.

```
setup_env.sh  eche10 eche10vis   -> python helao_env.py setup  eche10 eche10vis
update_env.sh                    -> python helao_env.py update
update_env.sh eche10             -> python helao_env.py update eche10
```

`helao_env.py` steps:

1. **Prefixes.** Use the arguments if given. Otherwise read every file listed in the
   conda env var `HELAO_STATION_PREFIXES` (`os.pathsep`-separated) and take the
   union. With no arguments and no variable, install nothing beyond the base env and
   print a hint to pass config prefixes.
   **Duplicate prefixes.** A prefix is matched against
   `helao/deploy/*/configs/<prefix>.*` in every nested deployment, private ones
   included (`read_config`, `helpers/config_loader.py`). When 2+ deployments match,
   `helao_env.py` lists the matches numbered by deployment and asks which one with
   `input()`. Without a tty it exits with the list instead of guessing. A prefix may
   also be given as `<deployment>/<prefix>` or as a full config path, which skips the
   prompt. The resolved full config path, not the bare prefix, is what gets recorded
   in step 5, so a no-argument `update` never prompts again. `launch.py` is
   unchanged and still raises on a duplicate prefix.
2. **Folders.** For each config, `read_config`, then resolve every server's
   `fast` / `bokeh` / `reflex` module with the launcher resolver (imported, not
   copied). Collect the containing server folders. An unresolvable module is a hard
   error.
3. **Conda first.** Merge the folders' `environment.yml` files (union of channels and
   dependencies) into one temporary file and run
   `conda env update -n helao --solver=rattler -f <tmp>` once. A conflicting pin fails
   the solve; report it and stop.
4. **pip second.** `uv pip install -r <folder>/requirements.txt` per folder. uv skips
   requirements conda already satisfied.
5. **Record.** For each config `root:`, merge the resolved config paths into
   `<root>/STATES/setup_env_prefixes.json` (create `STATES` if missing). Set
   `HELAO_STATION_PREFIXES` to the list of those file paths with
   `conda env config vars set`. Explicit prefixes passed to `update` are appended
   too.
6. **Vendor notes.** Print the folders whose `README.md` carries vendor SDK notes.
   Nothing is downloaded.

Rules:

- Platform-only dependencies go in `requirements.txt` with environment markers
  (`comtypes; sys_platform == "win32"`), because conda env files have no selectors.
- Hardware dependencies leave `helao_dev_<os>.yml` and `requirements.txt`, but only
  as the last step: after every private deployment ships its folder env files and
  every station has run `setup_env <its prefixes>` once (otherwise a no-argument
  `update_env` would drop drivers' packages). `pyftdi`, `pyft232` and `pyusb` have no
  importer anywhere and are removed outright. The `*_pinned_*` files cover the base
  env only and are regenerated with `repin_envs.py`.
- No uninstall and no `forget` command. To drop a prefix, edit the json.
- `update.sh` / `update.bat` are unchanged and do not call `update_env`.

### 4. Drivers that import hardware packages at module top

`serial` (alicat, legato, simdos, cm0134, sprintir), `pyvisa` (power_supply) and
`pylablib` (kinesis) are imported at module level. Without their deps those modules
fail at import time. That is acceptable once dependencies follow station configs: a
server that is launched has had its folder's deps installed. Tests that import these
modules on a machine without the deps report `ENV` through `run_tests.py`, as Windows
vendor SDKs already do. Making these imports lazy is out of scope.

## Phases and gates

Each phase ships alone. "Sweep parity" means the `run_tests.py` failing set equals
the baseline captured before the phase.

**P1. Resolver.** Add the resolver and switch every caller listed in section 2.
Remove the `hte` fallbacks.
Gates: resolver unit tests including the duplicate-name error; sweep parity; sim
launches of `goldenreflex` and the `test` configs.

**P2. Reorganize `hte`.** `git mv` into per-instrument folders, rewrite imports,
write env files, move hexagon adapters and tests, strip hardware deps from the base
env.
Gates: the 31 frozen route JSONs are unchanged except the `handler` module path;
a new test asserts that `helao/{core,hexagon,helpers,ui}` and the launchers contain
no `helao.deploy.hte` import and no `hte` path literal, and that test must fail on
the pre-P2 tree; sweep parity; sim launches.

**P3. `helao_env.py` and the four wrappers.**
Gates: fresh Linux env from prefixes, second run is a no-op; Windows dry-run solve of
the merged yml; no-argument `update` reproduces the same folder set from
`HELAO_STATION_PREFIXES`; a bad prefix or unresolvable module is a hard error; a
duplicate prefix prompts on a tty, exits without one, and `<deployment>/<prefix>`
skips the prompt. All
runs use a root under the job temp dir; nothing touches station roots or network
mounts.

**P4. `test` and private deployments.** Same pattern, each inside its own repo,
committed there. Private imports of `helao.deploy.hte.drivers.*` (about 26) are
rewritten to the new folder paths in the same change. Private code stays in private
repos.

**Rollout.** One station first: pull, `setup_env <its prefixes>`, launch, run one
action. Then the remaining stations.

## Out of scope: SiLA2 enhancement proposal

Reviewed separately on 2026-11-04. Summary, for later specs if wanted:

- Self-description: extend `/endpoints` (`hexagon/app/endpoint_manager.py`) with
  defaults, docstrings and enum choices, and expose it over RPC. Do not add a
  parallel msgspec schema layer; domain models are pydantic.
- Telemetry via ZMQ PUB/SUB: redundant with `/ws_live`, `/ws_data`, `/ws_status`,
  which already run apart from ZMQ RPC. Dropped.
- Lifecycle: add optional `progress` and `eta_s` to action status. A strict SiLA
  state machine conflicts with the list-of-`HloStatus` model and is not adopted.
