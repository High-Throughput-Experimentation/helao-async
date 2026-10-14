# HELAO config schema

A config file defines one **orchestration group**: the set of servers
`launch.py` starts together, plus the on-disk root they all write to. This
document covers the keys that are shared by every station and every server.
Driver-specific `params:` (COM ports, channel maps, device tables) are out of
scope — they are documented by the action server that reads them.

Two things read a config, and they disagree about what is required:

| Reader | When | Enforcement |
|---|---|---|
| `validateConfig` (`launch.py`) | at launch, after the stale-group check, before any server starts | aborts the whole group |
| `HelaoConfig` (`helao/helpers/config_loader.py`) | inside each server, at startup | raises `ValueError` in that server only |

The pre-launch unit-test gate (`run_unit_tests: true`) adds a third check:
`helao/core/tests/unit_test_config_validation.py` validates **every**
`helao/deploy/{hte,test}/configs/*.yml` on disk (tracked or not) against
`HelaoConfig`, so one broken config in those folders blocks every launch that
runs the gate. It prints to the console only; there is no log file.

`HelaoConfig` is a **schema gate and typed accessor, not a filter**. Servers
keep reading the raw dict (`self.world_cfg`, `self.server_cfg`); the validated
view silently ignores keys the model does not declare, and several keys the
runtime depends on are undeclared. Adding a key to a config does not require
adding it to `HelaoConfig`, and a key's absence from that model does not mean
nothing reads it. Orchestrator `params` are not type-checked at all: the
`OrchServerParams` model exists, but the `dict | OrchServerParams` annotation
matches `dict` first.

## Locating a config

`read_config` accepts a full path (`.yml` or `.py`) or a bare prefix. A prefix
is globbed against `helao/deploy/*/configs/<prefix>.*` across every deployment
in the tree, tracked and private alike, and it is an error for two deployments
to answer to the same prefix with the same extension; across extensions `.yml`
silently wins.

A `.py` config must define a top-level `config` dict; it is executed, not
parsed. `.yml` wins if both exist for one prefix.

### Naming a server's module (rule D-B7c.2)

A server names its own module in `fast:` or `bokeh:`, and the launcher
imports `helao.deploy.<deployment>.servers.<group>.<module>`. A `reflex:`
value names the Reflex app bundle (configs write `reflex: helao_ui`); it is
not resolved or imported. There is no second config per station and no
routing layer: a bare prefix launches the station, and the hexagon-native
hosts (`ActionHost`, `OrchHost`) serve it. The one optional key is
`deployment:`, which names the deployment that owns the module. It is required
when auto-detection is ambiguous, and on every `fast:`/`bokeh:` server of a
config that lives outside `helao/deploy/*/configs/`. See
[Deployment resolution](#deployment-resolution).

To check a config before launch:

```
python -m helao.hexagon.preflight <prefix or path>
```

It prints `PREFLIGHT OK` (exit 0), or `PREFLIGHT FAILED` (exit 1) and every
issue it found:

- config sanity: exactly one code key per server, `host`/`port` present, and
  `host:port` collisions, including a Reflex server's `port + 1` and a plate
  aligner's port;
- module resolution: every `fast:`/`bokeh:` module exists in a deployment the
  launcher searches; the retired `legacy_module:` and `deployment: hexagon`
  keys, a `fast:`/`bokeh:` value of `graft`, and a blank `deployment:` are
  reported;
- an `hte` action module whose endpoint checklist was frozen at B7c still has
  it (any other missing checklist prints as a note and does not fail);
- no function name appears in two modules of the same library list (see
  `allow_shadow`); entries preflight cannot resolve (own deployment, then
  `hte`) are skipped.

## Top-level keys

### Required in practice

| Key | Type | Notes |
|---|---|---|
| `root` | str | Output root. See [Root layout](#root-layout). |
| `run_type` | str | Free-form label, lower-cased; used as the run type of any experiment, sequence or manual action that does not set its own. |
| `servers` | map | Server key to server block. See [Server keys](#server-keys). |
| `dummy` | bool | See the warning below. |

`root` and `run_type` are required by `HelaoConfig`. Without `root`,
`launch.py` itself fails with a `TypeError` before any server starts; without
`run_type`, each server raises a `ValidationError` at startup.

> **`dummy` is effectively required, though the schema calls it optional.**
> `launch.py` reads `config["dummy"]` directly (no `.get`) while printing the
> launch banner, so a config without it fails with a `KeyError` before any
> server starts. `HelaoConfig` defaults it to `True`, but that default is never
> used. Every tracked `.yml` config sets `dummy`.

### Optional

| Key | Type | Default | Effect |
|---|---|---|---|
| `simulation` | bool | `True` (schema) / `False` (runtime readers) | Stamped onto every action, experiment and sequence record. No server or driver reads it; simulated hardware is selected per server (its `params`, or the module named in `fast:`). |
| `experiment_libraries` | list[str] | — | Modules whose `EXPERIMENTS` list the orchestrator publishes. |
| `sequence_libraries` | list[str] | — | Modules whose `SEQUENCES` list the orchestrator publishes. |
| `experiment_params` | dict | — | Default values for same-named arguments of experiment functions, pre-filled in the operator's parameter forms (Bokeh and Reflex). Items queued any other way do not see them. |
| `sequence_params` | dict | — | The same, for sequence functions. |
| `experiment_path` / `sequence_path` | str | `helao/deploy/<deployment>/{experiments,sequences}` | Overrides where library modules are looked up (`import_autolibs`). Undeclared in `HelaoConfig`. |
| `allow_shadow` | bool | `False` | Preflight only: allow the same function name in two library modules (the later one wins in the flat namespace). |
| `sync_finished` | bool | `True` | Declared in `HelaoConfig` and given a helper (`sync_finished_enabled`), but **no production code reads it yet**, so setting it changes nothing. Not the same as the per-record `sync_data` field. |
| `show_debug` | bool | `False` | **No effect in a launched group.** It is read only when a server builds its own logger, and every launcher builds the logger first without it. |
| `log_level` | int | `20` | File-log threshold for `launch.py` and every launched server (FastAPI, Bokeh, Reflex launcher); a server-level `log_level` overrides it for that server. Console output stays at INFO, and the Reflex backend child's `<key>_backend.log` stays at 20. |
| `run_unit_tests` | bool | `False` | `launch.py` runs `run_unit_tests.py` before launching and aborts on failure. |
| `hot_reload` | map | `{enabled: true, poll_seconds: 30}` | See [Hot reload](#hot-reload). |
| `alert_config_path` | str | — | Alert config (email and webhook). Overridden by the `ALERT_CONFIG_PATH` env var. |

Anything else at the top level is ignored by the framework and available to
deployment code through `world_cfg`. Reference-coordinate keys such as
`builtin_ref_motorxy` are of this kind: `HelaoConfig` declares the base name,
but the numbered variants (`builtin_ref_motorxy_2` and up) are looked up by
name (`world_cfg[ref_position_name]`) in the motion server, with the name
supplied by experiment code.

### Library list entries

Each entry of `experiment_libraries` / `sequence_libraries` may be either form,
and both appear in tracked configs:

```yaml
experiment_libraries:
  - simulatews_exp                                   # bare module name
  - helao/deploy/test/experiments/TEST_exp.py        # explicit path
```

A bare name resolves against the deployment's own library folder, which is
found in this order:

1. an explicit `experiment_path` / `sequence_path` in the config;
2. the deployment named by the config's own path — only a config at
   `helao/deploy/<deployment>/configs/` names one;
3. the deployment the launcher resolved for this server (`CONFIG["deployment"]`).

A bare name not found in that folder, or every name when no folder resolves,
falls back on its own: first `helao/deploy/hte/`, then a glob over every
deployment, with a warning at each step. Only then is `FileNotFoundError`
raised. A name present in several deployments but absent from the resolved
folder therefore resolves to `hte` if it is there, otherwise to whichever
deployment the unsorted glob returns first.

> **A config launched from outside the deploy tree cannot name its
> deployment.** Copying a station config into `USER_CONFIG`, editing it, and
> launching it by full path is supported, but step 2 above yields nothing, and
> step 3 depends on `deployment:` — see the warning under
> [Deployment resolution](#deployment-resolution). Set `deployment:` on every
> server in a config that lives outside `helao/deploy/*/configs/`.

### Launcher-injected keys

`read_config` and the launchers add these to the dict after loading. They are
not written in config files and not declared in `HelaoConfig`; most of them
are read at runtime:

| Key | Source |
|---|---|
| `loaded_config_path` | Absolute path of the resolved file. Pins the deployment for library and panel lookup. |
| `helao_repo_root` | Repo root, found by walking up from `config_loader.py`. |
| `helao_credentials_path` | `HELAO_CREDENTIALS` env var, or `""`. |
| `alert_config_path` | `ALERT_CONFIG_PATH` env var, if set. Overwrites the file's value. |
| `deployment` | Added by each launcher. FastAPI: the deployment the server's module was resolved from. Bokeh and Reflex: the server's explicit `deployment:`, else the name of the directory two levels above the config file. |
| `hlo_version` | Added by each launcher: the parent repo's version. |
| `deployment_version` | Added by each launcher: the version of that deployment's nested repo, or `hlo_version` if it has none. |

`fast_launcher.py` also sets the server-level `restore_queues_on_startup:
true` on orchestrators when `launch.py` runs with `--restore`.

## Root layout

`helao_dirs` creates the directories below under `root` — at startup for
FastAPI servers and the launcher, on first use for Bokeh and Reflex servers —
except `RUNS_SUPERSEDED/` and `FAULTS/`,
which are created by the code that first writes to them. A missing directory
is created without asking.

```
<root>/
  RUNS/             the single run tree; records are written once and never move
  RUNS_SUPERSEDED/  sequences retired through /retire (the one exception)
  DIAG/             manual (diagnostic) actions, a sibling of RUNS/
  LOGS/             <server_key>.log per server, rotated daily and gzipped
                    (old archives are not pruned)
  STATES/           pid pickles, queue exports, per-server run-state journals
                    (runstate_<server_key>.jsonl), loaded_modules_<key>.json,
                    reflex-bundles/, /retire ledgers
  DATABASE/
  USER_CONFIG/EXP, USER_CONFIG/SEQ
  ANALYSES/
  PROCESSES/
  FAULTS/           faulthandler crash dumps, <server_key>_faults.txt
                    (created at every FastAPI server's startup)
```

When `helao_dirs` runs, it also zips and removes any `*.txt` left under
`LOGS/<server_name>/` by the older per-directory logger, naming the archive
from the first timestamp in the file.

A record's lifecycle state (`active`, `unsynced`, `quarantined`, `done`) is
kept in the `STATES/runstate_*.jsonl` journals, not in its directory name. The
old `RUNS_ACTIVE`, `RUNS_FINISHED`, `RUNS_SYNCED`, `RUNS_DIAG` and
`RUNS_NOSYNC` directories are no longer written. Existing station archives
under those names are not migrated, and readers still resolve them. Spec:
`docs/superpowers/specs/2026-09-25-runs-layout-and-state-journal-design.md`.

> **`~` is not expanded.** `root: ~/INST_hlo` creates a literal directory named
> `~` inside the process's working directory — for a dev launch, inside the
> repo. Use an absolute path.

Because the layout is keyed on `root`, two configs sharing a `root` share
`STATES/queues.pck` and every per-server-key file (run-state journals,
loaded-module snapshots): two groups that both have a `SYNC` server write the
same journal. Pid pickles and Reflex bundles are named per config prefix and do
not collide. Give each orchestration group its own root.

## Server keys

Every entry of `servers:` is keyed by the **server key**, which is the name the
server is known by everywhere else: log file, pid table, dispatch target,
and the URL prefix of its action endpoints (`/<SERVER_KEY>/<action>`). Keys are
conventionally uppercase. Two keys are fixed by name: the syncer is `SYNC`,
and the analysis server is `ANA` (experiment libraries address it by that
name, and the orchestrator's status poll skips it).

### Required for every server

| Key | Type | Notes |
|---|---|---|
| `host` | str | Must be a string; validated at launch. |
| `port` | int | Must be an `int`, not a quoted string; validated at launch. |
| `group` | str | One of `action`, `orchestrator`, `operator`, `visualizer`. |

`group` selects the import path
(`helao.deploy.<deployment>.servers.<group>.<module>`), the launch order and
the kill order; the code key selects the launcher. `group` is validated as *a
string*, not against the known set: a typo'd group silently launches nothing,
because the launcher only iterates the four names it knows. For `fast:` /
`bokeh:` servers preflight catches it indirectly, as a module that exists in
no deployment the launcher searches; a `reflex:` server with a typo'd group
passes preflight and silently never starts.

### The code key

Exactly one of `fast`, `bokeh`, or `reflex` marks a managed server. Declaring
two is a launch-time error.

| Code key | Launcher | What the value names |
|---|---|---|
| `fast` | `fast_launcher.py` (uvicorn) | a module under `servers/<group>/` exposing `makeApp(server_key) -> HelaoFastAPI` |
| `bokeh` | `bokeh_launcher.py` (Bokeh `Server`) | a module under `servers/<group>/` exposing `makeBokehApp(doc, confPrefix, server_key, helao_repo_root)`, served at `/<module>` |
| `reflex` | `reflex_launcher.py` | the app bundle (`helao_ui`); only its presence matters, and the app imported is always `helao.ui.reflex.app` |

**Omitting the code key is legal for `launch.py`**: the server appears in the
config — so orchestrators dispatch to it and the address is reserved — but
`launch.py` does not start or monitor it. That is how a remotely started or
externally managed server is declared. Preflight does not model this case: it
reports such a server as "must declare exactly one of fast/bokeh/reflex", so
a config with an externally managed server cannot pass preflight.

### Optional, available to every server

| Key | Type | Read by |
|---|---|---|
| `params` | dict | The server's own `makeApp`. Free-form except for the group-level conventions below. |
| `deployment` | str | The deployment that owns the module; required when auto-detection is ambiguous, and for an out-of-tree config. See below. |
| `log_level` | int | Every launcher. Falls back to the top-level `log_level`, then `20`. |
| `regular_update` | bool | Action and orchestrator hosts: start a periodic status broadcast. |
| `regular_update_delay` | float | Seconds between those broadcasts. Default `10`. |
| `polling_time` | float | Action hosts whose driver has a poller: seconds between `get_data` polls. Default `0.1`. |
| `prefinish_hooks` | hook map | Action servers, including an orchestrator's own actions. See [Finish hooks](#finish-hooks). |
| `prefinish_experiment_hooks` / `prefinish_sequence_hooks` | hook map | Orchestrators. See [Finish hooks](#finish-hooks). |
| `postfinish_hooks` | hook map | The `SYNC` server. See [Finish hooks](#finish-hooks). |
| `action_vis` / `live_vis` / `control_vis` | str or list[str] | Names the visualizer/panel module(s) for this server. See [Visualizer wiring](#visualizer-wiring). |
| `restore_queues_on_startup` | bool | Orchestrators only. See [`group: orchestrator`](#group-orchestrator). |
| `verbose` | bool | **Nothing.** See the warning below. |

> **`verbose:` is declared but never read.** It appears in `ServerConfig` with
> the docstring "Enables debug-level logging on the server" and is set on
> about 20 servers across the tracked configs, but no code reads it. Use
> `log_level` (per server) to change the file-log level.

### Deployment resolution

Without a `deployment:` key, the launcher globs every deployment for
`servers/<group>/<module>.py`, and:

- one match — uses it, logging `Auto-detected deployment`;
- several matches — prefers the one under the config's own path, else takes
  the first and warns that an explicit `deployment:` key would disambiguate;
- no match — fails with `FileNotFoundError: Could not find deployment for
  <module> in <group>`.

Set `deployment:` on the server to pin it. For a config inside
`helao/deploy/*/configs/`, it is needed only when the module exists in two or
more deployments and none of them is the config's own (preflight reports
this). For a `reflex:` server, `deployment:` sets which deployment's panels
are searched first and, for an out-of-tree config, where the operator page
looks up bare library names.

> **A config outside `helao/deploy/*/configs/` resolves nothing.** The
> launcher globs from the config file's great-grandparent directory, which is
> `helao/deploy` only when the config lives in the tree. A station config
> copied to `USER_CONFIG` and launched by full path therefore finds no module,
> and each `fast:`/`bokeh:` server without `deployment:` exits at startup with
> `FileNotFoundError: Could not find deployment for ...`. Preflight reports
> each one as existing in no deployment the launcher searches. Set
> `deployment:` on every `fast:`/`bokeh:` server of an out-of-tree config.

### Visualizer wiring

An action server declares which visualizer renders it:

| Key | Bokeh app | Reflex page | WebSocket the ingest subscribes to |
|---|---|---|---|
| `action_vis` | `action_visualizer` | `/action` | `ws_data` |
| `live_vis` | `live_visualizer` | `/live` | `ws_live` |
| `control_vis` | `control_visualizer` | `/control` | — (reads and writes the server's endpoints) |

The value is a bare module name, or a list of names, resolved across
deployments: the configured deployment first, then `hte`, then every other
deployment that has a `servers/visualizer/` directory, alphabetically. The
same name serves both UI stacks: `servers/visualizer/<name>.py` for Bokeh,
`servers/reflex/<name>.py` for Reflex. A station therefore gains Reflex panels
by adding a `reflex:` server and changing nothing else, provided a Reflex
module of that exact name exists. Discovery does no suffix rewriting. Where
the Reflex panel has a different name, the deployment ships a re-export
module under the Bokeh name (for example `test/servers/reflex/wssim_live_vis.py`).

`control_vis` modules in `hte`: `digital_out_control`, `nidaqmx_control`,
`motion_control_letter_scale`, `motion_control_inverse_scale`,
`motion_control_name_scale`.

**A server with no `action_vis`/`live_vis` key gets no visualization at all**,
in either stack. This is the usual cause of an empty visualizer page. In the
same way, `/control` shows only its "none declared" note unless some server
declares `control_vis`.

For Reflex only, the key chooses the *page* while the panel module's
`WS_PATH` chooses which ingest the panel reads. The ingest itself is derived
from the key (`live_vis` → `ws_live`, `action_vis` → `ws_data`), so a panel
declared under `live_vis` whose `WS_PATH` is `ws_data` finds data only if the
same server also declares an `action_vis`.

A visualizer server's `params.limit_vis` (a server key or a list of them)
restricts the panels to those servers, including `control_vis` panels on
`/control` and in `control_visualizer`. Bokeh and Reflex both honour it.

## Finish hooks

Hooks run around a record's transition to `finished`, in two phases:

| Phase | Runs in | When | May change the record? |
|---|---|---|---|
| pre-finish | the server that owns the record: the action server for an action; the orchestrator (or `MicroOrch`) for an experiment or sequence | before the final yml is written and before `finished` is emitted | yes |
| post-finish | the `SYNC` server | after the record is finished | no |

A pre-finish hook that raises never stops the finish. The error is alerted and
appended to the record's `prefinish_errors` (`hook`, `error`, `ts`), and the
next hook runs. Post-finish failure depends on the hook's `blocking` (see
[Built-ins](#built-ins)).

All four keys are **server-level keys, not `params:`**:

| Key | On | Applies to |
|---|---|---|
| `prefinish_hooks` | each action server, and the orchestrator for its own actions | actions |
| `prefinish_experiment_hooks` | the orchestrator | experiments |
| `prefinish_sequence_hooks` | the orchestrator | sequences |
| `postfinish_hooks` | the `SYNC` server | `action:` / `experiment:` / `sequence:` sub-maps |

`MicroOrch` reads the two orchestrator keys (or their aliases) from the first
`group: orchestrator` entry in the config, unless its constructor is given
`prefinish_experiment_hooks` / `prefinish_sequence_hooks`.

### Hook map shape

```yaml
prefinish_hooks:
  hlo_to_csv: ["*"]                 # list form: record names, "*" = every record
  spec_melt_wls: [acquire]          # matched against action_name, not the abbr
  my_hook:                          # mapping form: record name -> args
    "*": {}
    SPECIAL_action: {threshold: 3}  # an exact name wins over "*" for args
```

Record names are `action_name` / `experiment_name` / `sequence_name`. Map
order is execution order. A hook whose map lists both the exact record name and
`"*"` runs once, with the args of the exact name.

### Resolving a hook name

1. a built-in, `helao/core/hooks/builtin/<name>.py`;
2. an existing `.py` path;
3. `helao/deploy/<this deployment>/processors/<name>.py`;
4. `helao/deploy/hte/processors/<name>.py`;
5. any `helao/deploy/*/processors/<name>.py` (sorted; the first match wins).

The module must define a `Hook` class (a `FinishHook`) or a `PostProcess`
class (an existing `HloPostProcessor`/`MetaProcessor`, run through an
adapter). Both adapted kinds are pre-finish only, and an `HloPostProcessor`
is valid at action level only (`prefinish_hooks`). Helper code under
`processors/libs/` is never matched.

### Built-ins

| Hook | Phase | Levels | Blocking | Args |
|---|---|---|---|---|
| `s3_upload` | post-finish | all | yes: a failure keeps the record unsynced and counts a strike (see [Sync quarantine](#sync-quarantine)) | — |
| `dispatch_analysis` | post-finish | experiment, sequence | no: a failure is recorded and the chain continues | `server_key` and `endpoint` (required); `params` (alias `analysis_params`); optional `host` + `port` |

`dispatch_analysis` checks its args when it runs, not at startup. A missing
`server_key`/`endpoint`, or a `server_key` that is neither given with
`host`+`port` nor present in the config, fails each record. A failed
non-blocking hook is not retried, and the record still counts as synced. To
re-run it, delete its entry from the `.prg`'s `hooks:` and set `synced: false`.

Processors shipped in `hte` (resolved by step 4 from any deployment):

| Hook | Kind | Phase | Levels | Effect |
|---|---|---|---|---|
| `hlo_to_csv` | `HloPostProcessor` | pre-finish | action | writes a `.csv` beside each `.hlo` and registers it as `csv__file` |
| `spec_melt_wls` | `HloPostProcessor` | pre-finish | action | melts spectral `.hlo` data to long-form parquet and replaces the file entry |
| `hispec_process_all` | `HloPostProcessor` | pre-finish | action | converts, calibrates and downsamples HiSpEC spectra to parquet |
| `append_params` | `MetaProcessor` | pre-finish | experiment, sequence | demo: adds a marker key to `experiment_params` / `sequence_params` |

Private deployments may add their own under
`helao/deploy/<deployment>/processors/`.

### Post-finish defaults

When `postfinish_hooks` is absent, the chain is `s3_upload: ["*"]` at every
level. If the SYNC server has `params.auto_analyze_sequences`, that value is
translated to `sequence: {dispatch_analysis: ...}`, with a deprecation
warning. **A present `postfinish_hooks` owns the whole chain.** Leave out
`s3_upload` and nothing uploads:

```yaml
SYNC:
  ...
  postfinish_hooks:
    action:     {s3_upload: ["*"]}
    experiment: {s3_upload: ["*"]}
    sequence:
      s3_upload: ["*"]
      dispatch_analysis:
        <sequence_name>: {server_key: <analysis server key>, endpoint: <endpoint>}
```

The syncer is found by server key: `SYNC`. A config that still carries the
retired `DB` key and no `SYNC` key raises at startup instead of silently not
syncing.

### Sync quarantine

Each failed sync pass (an exception in `sync_yml`, or a chain left unsynced by
a blocking hook) adds a strike to the `quarantine:` block in the record's
`.prg`. Once a record has `params.quarantine_strikes` strikes (default `5`)
and its first failure is at least `params.quarantine_hours` old (default
`24`), SYNC parks it: one alert, journal state `quarantined`, and no automatic
re-queue from then on, including the startup sweep. `quarantine_strikes: 0`
disables parking (strikes are still recorded). `/tasks` lists parked records,
and `POST /finish_yml` on a parked record releases and re-queues it. Spec:
`docs/superpowers/specs/2026-10-14-sync-quarantine-design.md`.

### Deprecated aliases

| Alias | Replacement |
|---|---|
| `hlo_postprocess_libs` | `prefinish_hooks` |
| `exp_postprocess_libs` | `prefinish_experiment_hooks` |
| `seq_postprocess_libs` | `prefinish_sequence_hooks` |
| SYNC `params.auto_analyze_sequences` | `postfinish_hooks.sequence.dispatch_analysis` |

A list alias `[a, b]` means `{a: ["*"], b: ["*"]}`. `auto_analyze_sequences`
is a mapping (sequence name → analysis block) and becomes the
`dispatch_analysis` args unchanged. Each alias logs one deprecation warning.

### Errors that stop startup

A bad hook config never quietly becomes "no hooks". Startup fails with
`HookConfigError` when:

- an alias and its replacement are both set, or a list alias is not a list of
  names;
- a map has the wrong shape (not a mapping, an empty list or mapping, a
  non-string record name, or args that are not a mapping);
- `postfinish_hooks` has a key other than `action`, `experiment` or
  `sequence`;
- a name resolves to nothing, or its module has no usable `Hook` /
  `PostProcess` class;
- a hook is configured for a phase or level it does not support.

A bad `postfinish_hooks` also fails the orchestrator's startup, because the
orchestrator builds its own syncer from the `SYNC` entry.

Full design: `docs/superpowers/specs/2026-09-28-finish-hooks-design.md`.

## Reflex UI pages

A Reflex server (`group: visualizer`, `reflex: helao_ui`) registers **every**
route, whatever its config says:

| Route | Content | What makes it show something |
|---|---|---|
| `/` | route index with panel counts | — |
| `/live` | `live_vis` panels | `pages` includes `live` and some server declares `live_vis` |
| `/action` | `action_vis` panels | `pages` includes `action` and some server declares `action_vis` |
| `/operator` | queue / experiment / sequence operator | an orchestrator in the config (the first `group: orchestrator` is used) |
| `/browser` | run-data browser | the config's `root` |
| `/control` | digital-out, DAQ and motion controls | some server declares `control_vis` |
| `/composition` | plate composition map | credentials (below), and some server declares `params.plate_api: HTEPlateAPI` |
| `/uvvis`, `/xafs`, `/xrds` | plate spectra | credentials (below); `/xafs` reads local analysis arrays under `root/ANALYSES` unless set to read from S3; the wafer-photo underlay also needs the plate API |
| `/retire` | retire mis-identified sequences | credentials (below), `params.retire: true` on this Reflex server, and a `root` |

**Credential-gated pages.** `/composition`, `/uvvis`, `/xafs`, `/xrds` and
`/retire` read the metadata API or S3. If the Reflex process has no
`HELAO_CREDENTIALS` environment variable naming an existing file, their
navigation links are hidden and each page shows a note instead of its
content. This is decided when the UI runs, not when the bundle is built:
setting the variable and restarting the UI brings the pages back with no
rebuild.

> **`params.pages` does not decide which pages exist.** It only chooses which
> panels mount on `/live` and `/action`. The default is `[live, action]`, and
> an empty list also means the default. Only `live` and `action` have an
> effect; other values (`operator`, `browser`, …) are accepted and ignored. A
> page left out of `pages` still renders, with the note "No server in this
> config declares a `live_vis` panel" (or `action_vis`), even when servers do.
> Write it as a list: the code accepts a bare `pages: live`, but
> `pages: [live]` is the form to use.

Params on the Reflex server entry:

| Param | Default | Effect |
|---|---|---|
| `pages` | `[live, action]` | See above. |
| `limit_vis` | — | Only these server keys contribute panels (`/live`, `/action`, `/control`). A bare string is treated as a one-item list. It does not limit which servers the backend subscribes to. |
| `poll_interval` | `5` | Operator page poll cadence in seconds. A value that is not a positive number falls back to `5`. |
| `plate_api` | — | `HTEPlateAPI` is the only accepted value. `/operator` reads this server's own value. `/composition` and the spectra pages use the first server in the config that declares one. |
| `retire` | `False` | Literal `true` enables `/retire`. The page deletes metadata-API rows and moves run directories, so turn it on only where intended. |
| `retire_sources_root` | — | Folder of converter sources. `/retire` refuses a sequence that has a converter job still in progress under this folder. |
| `seqspec_parser_path` / `seqspec_folder_path` / `parser_kwargs` | — | Spec-sequence tab of `/operator`. The two paths resolve relative to the repo root when not absolute. See [`group: operator`](#group-operator). |

The Reflex `/operator` page ignores `orch_key` and always attaches to the
first orchestrator in the config.

The frontend bundle is built per (config, Reflex server) under
`<root>/STATES/reflex-bundles/<config_prefix>_<server_key>/` (or
`<repo>/.reflex-bundle/<config_prefix>_<server_key>/` when the config has no
`root`). It is rebuilt at launch when its stamp (backend URL, config prefix,
server key, repo revisions and uncommitted changes, loaded modules, tool
versions) no longer matches — if bun or node is on PATH and either
`_app/.web/node_modules` exists or `REFLEX_ALLOW_LOCAL_BUILD=1` is set.
Otherwise the server logs the build command and exits. The stamp does not
hash the config file itself, so an edit to an untracked config may not trigger
a rebuild. On a noexec mount `HELAO_REFLEX_BUILD_DIR` overrides the build
staging directory. See `helao/ui/reflex/CLAUDE.md`.

## Ports

Beyond the declared `port`, servers claim ports implicitly. `validateConfig`
checks only the Reflex backend; preflight also checks the aligner port;
nothing checks the RPC port:

| Consumer | Port | Checked by `validateConfig`? |
|---|---|---|
| The server itself | `port` | yes |
| Reflex backend | `port + 1` | yes — `reserved_addresses` returns both |
| Plate-aligner Bokeh (`params.enable_aligner`) | `params.bokeh_port`, else `port + 1000` | **no** (preflight checks it) |
| ZMQ RPC (every FastAPI server) | `port + 10000` | **no** |

`validateConfig` rejects duplicate `host:port` pairs across the group. It does
not model the RPC offset, so two servers 10000 apart pass validation and then
collide at runtime: whichever binds second fails. If that is the RPC socket,
it retries on the `0.0.0.0` wildcard with a warning — which listens on
*every* interface — and if that bind also fails the server's startup aborts.
Keep station ports well inside a 10000-wide band.

The RPC socket binds to the configured `host`. When that name does not resolve
to a locally assigned address (a FQDN whose DNS points elsewhere, for
instance), the bind fails where uvicorn's would have succeeded, and the same
wildcard fallback applies.

## Group conventions for `params:`

`params` is free-form and forwarded to the server's `makeApp`, but each group
has keys the shared framework code reads.

### `group: action`

Shared by every action server (`ActionHost`):

| Param | Default | Effect |
|---|---|---|
| `allow_concurrent_actions` | `True` | `False`: an action whose endpoint is busy is parked in one server-wide queue, released when no endpoint is running an action; an action for an idle endpoint starts at once. `True`: parked per endpoint. `start_condition: no_wait` bypasses either. Some `hte` servers force `False` in code. |
| `enable_aligner` / `bokeh_port` | — / `port + 1000` | Motion servers: host the Bokeh plate aligner on a second port. Preflight reserves it; `validateConfig` does not. |
| `positions` | — | Sample-archive positions. At most one server per config may declare it (see [Validation rules](#validation-rules)). |

`SYNC` (`sync_server`, `HelaoSyncer`). An orchestrator or other host that
builds a syncer without its own `aws_config_path` reads these from the `SYNC`
entry:

| Param | Default | Effect |
|---|---|---|
| `aws_profile` | `default` | Section of the INI file named by the `AWS_CONFIG_PATH` environment variable. Its keys (`aws_access_key_id`, `aws_secret_access_key`, `region`, `aws_bucket`, …) are merged into `params`. |
| `aws_config_path` | — | Path to that INI. **Setting it in the config does not read the file**: credentials must then be inline in `params`, or startup raises `KeyError`. Use the environment variable. |
| `aws_bucket` | — | Required, from `params` or the profile. A missing bucket raises at startup. |
| `max_tasks` | `1` | Concurrent sync tasks. |
| `sync_pending_on_startup` | `True` | Sweep and enqueue unsynced records at startup. `False` leaves them for `/finish_pending`. |
| `quarantine_strikes` | `5` | See [Sync quarantine](#sync-quarantine). `0` disables parking. |
| `quarantine_hours` | `24` | See [Sync quarantine](#sync-quarantine). |
| `auto_analyze_sequences` | — | Deprecated; see [Deprecated aliases](#deprecated-aliases). |
| `testing` | — | **Nothing reads it.** |

`ANA` (`analysis_server`):

| Param | Default | Effect |
|---|---|---|
| `analyses` | `[]` | Module names, or `module:ClassName`. Each becomes an `analyze_<module>` endpoint. One that fails to load aborts startup. |
| `local_only` | `False` | Write analysis outputs locally; skip the S3 upload. |
| `env_file` | `helao_credentials_path`, then `$HELAO_CREDENTIALS` | Credentials env file. |
| `max_tasks` | `1` | Concurrent analyses. |
| `analysis_recovery_on_startup` | `True` | Sweep the analysis request journal at startup. |
| `analysis_recovery_max_per_startup` | `250` | Entries per sweep batch (it bounds every batch, not only the first). |
| `analysis_recovery_drain_when_idle` | `True` | Keep draining the journal in slices while idle. |
| `analysis_recovery_idle_poll_seconds` | `30` | Idle-check cadence for that drain. |

### `group: orchestrator`

| Param | Default | Effect |
|---|---|---|
| `heartbeat_interval` | `10.0` | Seconds between probes of the endpoints of active actions (an unreachable one stops the orchestrator) and between the `get_status` polls behind `status_summary`. |
| `ignore_heartbeats` | `[]` | Endpoints, written `SERVER_KEY/endpoint` (e.g. `ANDOR/acquire`), whose unreachability during a run does not stop the orchestrator. A bare server key matches nothing. |
| `verify_plates` | `True` | Applies only when the plate API has credentials. A `plate_id` in sequence or experiment params that the API cannot find stops the orchestrator. |
| `split_by_seq_params` | `[]` | Sequence params whose list value splits one sequence into several on "add split sequences" (the operator's split plan). If several are present, the first in the sequence's parameter order wins. |
| `group_by_seq_params` | `[]` | With a split, a sequence param whose list marks where each sub-sequence ends. |
| `enable_op` | — | **Deprecated and ignored.** The operator is a separate `group: operator` server now. |

An action server whose own `params` contains `ignore_heartbeats` (any value)
is also left out of the orchestrator's `get_status` poll.

Queue restore is a server-level key, not a param: `restore_queues_on_startup:
true` makes this orchestrator import `STATES/queues.pck` on every start. The
`--restore` CLI flag sets the same thing for one launch. A restored pickle is
archived so it is not replayed twice. On import, `loop_state` returns to
`stopped` (an E-STOP latch is kept) and `loop_intent` to none. Each in-flight
action of the restored active experiment is re-queued at the front as a fresh
copy (new uuid, `action_retry + 1`). Every in-flight uuid, re-run or not, is
retired as skipped.

### `group: operator`

| Param | Default | Effect |
|---|---|---|
| `orch_key` | first `group: orchestrator` server | Bokeh operator: which orchestrator in this config to attach to. The Reflex `/operator` page ignores it. |
| `poll_interval` | `5.0` | Seconds between queue/status polls. |
| `plate_api` | — | Named plate API backend. Only `HTEPlateAPI` is accepted; another name is ignored (Reflex logs a warning; Bokeh is silent). |
| `doc_name` | `<key> Bokeh App` | Bokeh document title. |
| `seqspec_folder_path` | — | Folder of sequence-spec files. |
| `seqspec_parser_path` | — | Path to the deployment's `SpecParser` module. |
| `parser_kwargs` | `{}` | Extra keyword arguments for the spec parser. Both stacks. |
| `skip_default_highlights` | `[]` | Bokeh operator: parameter names not highlighted when left at their default. |

> **`seqspec_*` must be on the UI server that shows the operator, not the
> orchestrator.** The Bokeh operator (a `group: operator` server) and the
> Reflex `/operator` page (the `reflex:` server, usually `group: visualizer`)
> each read these keys from their **own** server entry's `params`. Under
> `ORCH.params` they have no effect. The Reflex spec tab then reports that no
> spec parser is configured, and the Bokeh spec list stays empty with no
> message.

### `group: visualizer`

| Param | Default | Effect |
|---|---|---|
| `doc_name` | `<key> Bokeh App` | Bokeh document title. |
| `launch_browser` | `False` | Open a browser tab when the app starts. |
| `max_points` | `50000` | Data browser only: trailing-window size. The action/live visualizer panels ignore it. |
| `update_rate` | `0.5` (live), `0.001` (action) | Bokeh panels: minimum seconds between WebSocket reads. |
| `limit_vis` | — | Only these server keys are visualized, including control panels. Bokeh and Reflex. Write a list: Bokeh tests a bare string as a substring. |
| `pages`, `retire`, … | — | Reflex only. See [Reflex UI pages](#reflex-ui-pages). |

## Validation rules

`validateConfig` aborts the launch when:

1. `servers` is missing (this currently surfaces as a `KeyError` traceback,
   not the logged message);
2. any server lacks `host`, `port`, or `group`;
3. `host` is not a string, `port` is not an int, or `group` is not a string;
4. a server declares more than one of `fast` / `bokeh` / `reflex`, or declares
   one that is not a string;
5. two servers claim the same `host:port` (counting a Reflex server's
   `port + 1`);
6. **more than one server declares `params.positions`.** Sample-archive state
   is a single-owner resource; two owners race on the shared state JSON.

`validateConfig` runs after the check for a group that is still running, so
`--force-relaunch` with an invalid config tears the old group down and then
refuses to launch. Run preflight first.

Per-server module existence is *not* checked — that block is commented out, so
a mistyped `fast:` / `bokeh:` value fails later, inside that server's
launcher, as `Could not find deployment for <module>` (or an import error when
`deployment:` is set). Preflight reports it before launch.

## Hot reload

```yaml
hot_reload:
  enabled: true      # default
  poll_seconds: 30   # default; truncated to an int, values below 1 become 1
```

The watcher polls the parent repo and each nested deployment repo; on any
HEAD change (pull, commit or checkout) it restarts the idle servers whose
loaded code changed. Orchestrators restart only when idle, and come back with
`--restore`. Once a teardown starts (CTRL-x or a signal), the watcher stops
and no restart runs.

Precedence: `--no-hot-reload` beats `--hot-reload` beats the config key.
`CTRL-t` toggles the watcher at runtime.

## Worked example

```yaml
dummy: true
simulation: true
run_unit_tests: true
run_type: simulation
root: /home/dan/INST_hlo_golden

experiment_libraries:
  - simulatews_exp
  - helao/deploy/test/experiments/TEST_exp.py
sequence_libraries:
  - helao/deploy/test/sequences/TEST_seq.py

servers:
  ORCH:
    host: 127.0.0.1
    port: 8001
    group: orchestrator
    fast: async_orch2
    params: {}
    prefinish_experiment_hooks:
      append_params: ["*"]
    prefinish_sequence_hooks:
      append_params: ["*"]

  SIM:
    host: 127.0.0.1
    port: 8002
    group: action
    fast: ws_simulator
    live_vis: wssim_live_vis          # names the panel; without it, no plots
    params: {}
    prefinish_hooks:
      hlo_to_csv: ["*"]

  UI:
    host: 127.0.0.1
    port: 5010                        # Reflex also claims 5011
    group: visualizer
    reflex: helao_ui
    params:
      pages: [live, action]

  OPERATOR:
    host: 127.0.0.1
    port: 5001
    group: operator
    bokeh: standalone_operator
    params:
      orch_key: ORCH
      doc_name: "Operator (golden capture)"
      poll_interval: 5
```

Ports here occupy `8001`/`8002`/`5001`/`5010`, plus `5011` for the Reflex
backend, and, implicitly, `18001`/`18002` for RPC. The example has no `SYNC`
server, so nothing it records is uploaded.

## Checklist for a new station config

- [ ] `root` is absolute, not `~`-relative, and not shared with another group
- [ ] `dummy` is present (a missing key is a `KeyError` at launch, not a default)
- [ ] `run_type` set — it labels every record that does not set its own
- [ ] every server has `host`, `port` (an int), `group`
- [ ] exactly one code key per managed server (a server with none is not
      launched, but preflight reports it)
- [ ] no server's `port + 10000` equals another server's port
- [ ] a Reflex server's `port + 1` is free
- [ ] an aligner server's `bokeh_port` (or `port + 1000`) is free
- [ ] every action server that should be visualized names `action_vis` or
      `live_vis`
- [ ] at most one server declares `params.positions`
- [ ] the Bokeh operator names the right `orch_key`, and each operator UI
      carries its own `seqspec_*` params
- [ ] finish hooks use `prefinish_*` / `postfinish_hooks`, not the deprecated
      `*_postprocess_libs` lists
- [ ] a `postfinish_hooks` block still lists `s3_upload` at every level that
      should upload
- [ ] the syncer server is keyed `SYNC`, and `ignore_heartbeats` entries are
      `SERVER_KEY/endpoint`
- [ ] Reflex `pages` is a list; `retire: true` only where retiring is intended
- [ ] if the file lives outside `helao/deploy/*/configs/`, every `fast:` /
      `bokeh:` server carries an explicit `deployment:`
- [ ] `python -m helao.hexagon.preflight <prefix>` prints `PREFLIGHT OK`, and
      `python launch.py <prefix>` logs `Configuration for '<prefix>' is
      valid.` (reaching the banner alone does not prove validation: it runs
      after the countdown)
