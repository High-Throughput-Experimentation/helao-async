# HELAO config schema

A config file defines one **orchestration group**: the set of servers
`launch.py` starts together, plus the on-disk root they all write to. This
document covers the keys that are shared by every station and every server.
Driver-specific `params:` (COM ports, channel maps, device tables) are out of
scope — they are documented by the action server that reads them.

Two things read a config, and they disagree about what is required:

| Reader | When | Enforcement |
|---|---|---|
| `validateConfig` (`launch.py`) | at launch, before any server starts | aborts the whole group |
| `HelaoConfig` (`helao/helpers/config_loader.py`) | inside each server, at startup | raises `ValueError` in that server only |

The pre-launch unit-test gate (`run_unit_tests: true`) adds a third check:
`helao/core/tests/unit_test_config_validation.py` validates **every** tracked
`helao/deploy/{hte,test}/configs/*.yml` against `HelaoConfig`, so one broken
config in those folders blocks every launch that runs the gate. It prints to
the console only; there is no log file.

`HelaoConfig` is a **schema gate and typed accessor, not a filter**. Servers
keep reading the raw dict (`self.world_cfg`, `self.server_cfg`); the validated
view silently ignores keys the model does not declare, and several keys the
runtime depends on are undeclared. Adding a key to a config does not require
adding it to `HelaoConfig`, and a key's absence from that model does not mean
nothing reads it.

## Locating a config

`read_config` accepts a full path (`.yml` or `.py`) or a bare prefix. A prefix
is globbed against `helao/deploy/*/configs/<prefix>.*` across every deployment
in the tree, tracked and private alike, and it is an error for two deployments
to answer to the same prefix.

A `.py` config must define a top-level `config` dict; it is executed, not
parsed. `.yml` wins if both exist for one prefix.

### Derived `<name>_hex.py` configs

A `<name>_hex.py` beside a station's `<name>.yml` is not a second copy. It
calls `helao.hexagon.hexconfig.hexagon_variant(<absolute path of <name>.yml>)`
(built from `__file__`), which loads the
base and re-composes every server onto the hexagon app layer. Edit the base;
the variant follows. Per server the variant adds:

- `deployment: hexagon` on every server;
- for a non-orchestrator, non-Reflex server with no matching hexagon shim
  (none of that name, or one pointing at a different module), also
  `<code key>: graft` and a `legacy_module:` naming the real target.

`root:`, ports and `params:` are unchanged, so both variants write to the same
tree. Do not add these keys by hand. To see what a variant resolves to:

```
python -m helao.hexagon.preflight helao/deploy/<deployment>/configs/<name>_hex.py
```

## Top-level keys

### Required in practice

| Key | Type | Notes |
|---|---|---|
| `root` | str | Output root. See [Root layout](#root-layout). |
| `run_type` | str | Free-form label; lower-cased into every action/experiment/sequence record. |
| `servers` | map | Server key to server block. See [Server keys](#server-keys). |
| `dummy` | bool | See the warning below. |

`root` and `run_type` are required by `HelaoConfig`; a server missing either
raises at startup rather than running unlabelled.

> **`dummy` is effectively required, though the schema calls it optional.**
> `launch.py` reads `config["dummy"]` directly (no `.get`) while printing the
> launch banner, so a config without it fails with a `KeyError` before any
> server starts. `HelaoConfig` defaults it to `True`, but that default is never
> used. Every tracked `.yml` config sets `dummy`. The derived `_hex.py` configs
> inherit it from their base.

### Optional

| Key | Type | Default | Effect |
|---|---|---|---|
| `simulation` | bool | `True` (schema) / `False` (runtime readers) | Stamped onto every action, experiment and sequence record. Most action servers also select simulated drivers on it. |
| `experiment_libraries` | list[str] | — | Modules whose `EXPERIMENTS` list the orchestrator publishes. |
| `sequence_libraries` | list[str] | — | Modules whose `SEQUENCES` list the orchestrator publishes. |
| `experiment_params` | dict | — | Defaults merged into experiments at runtime. |
| `sequence_params` | dict | — | Defaults merged into sequences at runtime. |
| `experiment_path` / `sequence_path` | str | `helao/deploy/<deployment>/{experiments,sequences}` | Overrides where library modules are looked up (`import_autolibs`). Undeclared in `HelaoConfig`. |
| `sync_finished` | bool | `True` | Declared in `HelaoConfig` and given a helper (`sync_finished_enabled`), but **no production code reads it yet**, so setting it changes nothing. Not the same as the per-record `sync_data` field. |
| `show_debug` | bool | `False` | Console handler at DEBUG instead of INFO. File logs are unaffected. |
| `log_level` | int | `20` | Log level for `launch.py` and for every launcher (FastAPI, Bokeh, Reflex). A server-level `log_level` overrides it. |
| `run_unit_tests` | bool | `False` | `launch.py` runs `run_unit_tests.py` before launching and aborts on failure. |
| `hot_reload` | map | `{enabled: true, poll_seconds: 30}` | See [Hot reload](#hot-reload). |
| `alert_config_path` | str | — | Email-alert config. Overridden by the `ALERT_CONFIG_PATH` env var. |

Anything else at the top level is ignored by the framework and available to
deployment code through `world_cfg`. Reference-coordinate keys such as
`builtin_ref_motorxy` are of this kind: `HelaoConfig` declares the base name,
but the numbered variants (`builtin_ref_motorxy_2` and up) are read by name
from experiment code, not by the framework.

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

If none of those is a real directory, each library is resolved on its own:
first under `hte`, then by globbing every deployment, warning at each step.
Only if that fails too does it raise `FileNotFoundError`. So an unresolvable
name is a late, loud failure — but a name that exists in two deployments
resolves to whichever the glob returns first.

> **A config launched from outside the deploy tree cannot name its
> deployment.** Copying a station config into `USER_CONFIG`, editing it, and
> launching it by full path is supported, but step 2 above yields nothing, and
> step 3 depends on the launcher having guessed right — see the warning under
> [Deployment resolution](#deployment-resolution). Set `deployment:` on every
> server in a config that lives outside `helao/deploy/*/configs/`.

### Launcher-injected keys

`read_config` adds these to the dict after loading. They are not written in
config files, they are not declared in `HelaoConfig`, and code does depend on
them:

| Key | Source |
|---|---|
| `loaded_config_path` | Absolute path of the resolved file. Pins the deployment for library and panel lookup. |
| `helao_repo_root` | Repo root, found by walking up from `config_loader.py`. |
| `helao_credentials_path` | `HELAO_CREDENTIALS` env var, or `""`. |
| `alert_config_path` | `ALERT_CONFIG_PATH` env var, if set. Overwrites the file's value. |
| `deployment` | Added by each launcher after resolving the server's deployment. |

## Root layout

`helao_dirs` creates these under `root` at startup, per server, and returns the
resolved paths. A missing directory is created without asking.

```
<root>/
  RUNS/           the single run tree; records are written once and never move
  RUNS_SUPERSEDED/  sequences retired through /retire (the one exception)
  DIAG/           manual (diagnostic) actions, a sibling of RUNS/
  LOGS/           per-server rotating text logs
  STATES/         pid pickles, queue exports, Bokeh module snapshots,
                  per-server run-state journals (runstate_<server_key>.jsonl)
  DATABASE/
  USER_CONFIG/EXP, USER_CONFIG/SEQ
  ANALYSES/
  PROCESSES/
  FAULTS/         asyncio hang-inspection dumps (created on first hang)
```

On startup each server zips and removes any leftover `*.txt` under
`LOGS/<server_name>/`, naming the archive from the first timestamp inside the
log.

A record's lifecycle state (active, finished, synced) is kept in the
`STATES/runstate_*.jsonl` journals, not in its directory name. The old
`RUNS_ACTIVE`, `RUNS_FINISHED`, `RUNS_SYNCED`, `RUNS_DIAG` and `RUNS_NOSYNC`
directories are no longer written. Existing station archives under those names
are not migrated, and readers still resolve them. Spec:
`docs/superpowers/specs/2026-09-25-runs-layout-and-state-journal-design.md`.

> **`~` is not expanded.** `root: ~/INST_hlo` creates a literal directory named
> `~` inside the process's working directory — for a dev launch, inside the
> repo. Use an absolute path.

Because the layout is keyed on `root`, two configs sharing a `root` share
their `STATES/` — including pid pickles and exported queues. Give each
orchestration group its own root.

## Server keys

Every entry of `servers:` is keyed by the **server key**, which is the name the
server is known by everywhere else: log directory, pid table, dispatch target,
and the URL prefix of its action endpoints (`/<SERVER_KEY>/<action>`). Keys are
conventionally uppercase.

### Required for every server

| Key | Type | Notes |
|---|---|---|
| `host` | str | Must be a string; validated at launch. |
| `port` | int | Must be an `int`, not a quoted string; validated at launch. |
| `group` | str | One of `action`, `orchestrator`, `operator`, `visualizer`. |

`group` selects the launcher, the import path
(`helao.deploy.<deployment>.servers.<group>.<module>`), the launch order, and
the kill order. It is validated as *a string*, not against the known set: a
typo'd group silently launches nothing, because the launcher only iterates the
four names it knows.

### The code key

Exactly one of `fast`, `bokeh`, or `reflex` names the module under
`servers/<group>/`. Declaring two is a launch-time error.

| Code key | Launcher | Factory the module must expose |
|---|---|---|
| `fast` | `fast_launcher.py` (uvicorn) | `makeApp(server_key) -> HelaoFastAPI` |
| `bokeh` | `bokeh_launcher.py` (Bokeh `Server`) | `makeBokehApp(...)` |
| `reflex` | `reflex_launcher.py` | serves a prebuilt bundle |

**Omitting the code key is legal and meaningful**: the server appears in the
config — so orchestrators dispatch to it and the address is reserved — but
`launch.py` does not start or monitor it. That is how a remotely started or
externally managed server is declared.

### Optional, available to every server

| Key | Type | Read by |
|---|---|---|
| `params` | dict | The server's own `makeApp`. Free-form except for the group-level conventions below. |
| `deployment` | str | Overrides deployment auto-detection. See below. |
| `log_level` | int | Every launcher. Falls back to the top-level `log_level`, then `20`. |
| `regular_update` | bool | Action and orchestrator hosts: start a periodic status broadcast. |
| `regular_update_delay` | float | Seconds between those broadcasts. Default `10`. |
| `prefinish_hooks` | hook map | Action servers only. See [Finish hooks](#finish-hooks). |
| `action_vis` / `live_vis` / `control_vis` | str or list[str] | Names the visualizer/panel module(s) for this server. See [Visualizer wiring](#visualizer-wiring). |
| `restore_queues_on_startup` | bool | Orchestrators only. See [`group: orchestrator`](#group-orchestrator). |
| `verbose` | bool | **Nothing.** See the warning below. |

> **`verbose:` is declared but never read.** It appears in `ServerConfig` with
> the docstring "Enables debug-level logging on the server" and is set on
> dozens of servers across the tracked configs, but no code reads it. Use
> `log_level` (per server) or `show_debug` (whole group) to actually change
> logging.

### Deployment resolution

Normally the deployment is inferred from where the config file lives:
`helao/deploy/<deployment>/configs/<prefix>.yml`. When the named module does
not exist there, the launcher globs every deployment for it and:

- one match — uses it, logging `Auto-detected deployment`;
- several matches — prefers the one under the config's own path, else takes
  the first and warns that an explicit `deployment:` key would disambiguate;
- no match — fails.

Set `deployment:` on the server to pin it. This is how a generic app
(`live_visualizer`, `action_visualizer`) gets reused from one deployment by a
config that lives in another.

> **A config outside `helao/deploy/*/configs/` disables the tie-breaker.** The
> "prefer the deployment under the config's own path" rule has nothing to
> match on, so a module name that several deployments provide resolves to the
> alphabetically first one — with a warning, but the group still launches. A
> station config copied to `USER_CONFIG` and launched by full path can
> therefore start a *different implementation* of a server than the same file
> starts in place. `async_orch2`, for one, exists in more than one deployment.
> Always set `deployment:` on the servers of an out-of-tree config.

### Visualizer wiring

An action server declares which visualizer renders it:

| Key | Bokeh app | Reflex page | WebSocket the ingest subscribes to |
|---|---|---|---|
| `action_vis` | `action_visualizer` | `/action` | `ws_data` |
| `live_vis` | `live_visualizer` | `/live` | `ws_live` |
| `control_vis` | `control_visualizer` | `/control` | — (reads and writes the server's endpoints) |

The value is a bare module name, or a list of names, resolved across
deployments (configured deployment first, then `hte`, then the rest
alphabetically). The same name serves both UI stacks:
`servers/visualizer/<name>.py` for Bokeh, `servers/reflex/<name>.py` for
Reflex. A station therefore gains Reflex panels by adding a `reflex:` server
and changing nothing else, provided a Reflex module of that exact name exists.
Discovery does no suffix rewriting. Where the Reflex panel has a different
name, the deployment ships a re-export module under the Bokeh name (for
example `test/servers/reflex/wssim_live_vis.py`).

`control_vis` modules in `hte`: `digital_out_control`, `nidaqmx_control`,
`motion_control_letter_scale`, `motion_control_inverse_scale`,
`motion_control_name_scale`.

**A server with no `action_vis`/`live_vis` key gets no visualization at all**,
in either stack. This is the usual cause of an empty visualizer page. In the
same way, `/control` shows only its "none declared" note unless some server
declares `control_vis`.

For Reflex only, the key chooses the *page* while the panel module's `WS_PATH`
chooses the *socket*; a panel declared under `live_vis` may still read
`ws_data`.

A visualizer server's `params.limit_vis` (a server key or a list of them)
restricts the panels to those servers. Bokeh and Reflex both honour it.

## Finish hooks

Hooks run around a record's transition to `finished`, in two phases:

| Phase | Runs in | When | May change the record? |
|---|---|---|---|
| pre-finish | the server that owns the record: the action server for an action; the orchestrator (or `MicroOrch`) for an experiment or sequence | before the final yml is written and before `finished` is emitted | yes |
| post-finish | the `SYNC` server | after the record is finished | no |

All four keys are **server-level keys, not `params:`**:

| Key | On | Applies to |
|---|---|---|
| `prefinish_hooks` | each action server | actions |
| `prefinish_experiment_hooks` | the orchestrator | experiments |
| `prefinish_sequence_hooks` | the orchestrator | sequences |
| `postfinish_hooks` | the `SYNC` server | `action:` / `experiment:` / `sequence:` sub-maps |

`MicroOrch` reads the two orchestrator keys from the first `group:
orchestrator` entry in the config.

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
is valid at action level only (`prefinish_hooks`).

Built-ins:

| Hook | Phase | Levels | Blocking | Args |
|---|---|---|---|---|
| `s3_upload` | post-finish | all | yes: a failure keeps the record unsynced | — |
| `dispatch_analysis` | post-finish | experiment, sequence | no: a failure is recorded and the chain continues | `server_key` and `endpoint` (required); `params` (alias `analysis_params`); optional `host` + `port` |

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

- an alias and its replacement are both set;
- a map has the wrong shape (an empty list, or args that are not a mapping);
- `postfinish_hooks` has a key other than `action`, `experiment` or
  `sequence`;
- a name resolves to nothing;
- a hook is configured for a phase or level it does not support.

Full design: `docs/superpowers/specs/2026-09-28-finish-hooks-design.md`.

## Reflex UI pages

A Reflex server (`group: visualizer`, `reflex: helao_ui`) registers **every**
route, whatever its config says:

| Route | Content | What makes it show something |
|---|---|---|
| `/` | landing page | — |
| `/live` | `live_vis` panels | `pages` includes `live` and some server declares `live_vis` |
| `/action` | `action_vis` panels | `pages` includes `action` and some server declares `action_vis` |
| `/operator` | queue / experiment / sequence operator | an orchestrator in the config (the first `group: orchestrator` is used) |
| `/browser` | run-data browser | — |
| `/control` | digital-out, DAQ and motion controls | some server declares `control_vis` |
| `/composition` | plate composition map | credentials (below), and some server declares `params.plate_api: HTEPlateAPI` |
| `/uvvis`, `/xafs`, `/xrds` | plate spectra | credentials (below); the wafer-photo underlay also needs the plate API |
| `/retire` | retire mis-identified sequences | credentials (below), `params.retire: true` on this Reflex server, and a `root` |

**Credential-gated pages.** `/composition`, `/uvvis`, `/xafs`, `/xrds` and
`/retire` read the metadata API or S3. If the Reflex process has no
`HELAO_CREDENTIALS` environment variable naming an existing file, their
navigation links are hidden and each page shows a note instead of its
content. This is decided when the UI runs, not when the bundle is built:
setting the variable and restarting the UI brings the pages back with no
rebuild.

> **`params.pages` does not decide which pages exist.** It only chooses which
> panels mount on `/live` and `/action`. The default is `[live, action]`. A
> page left out of `pages` still renders, with a note that it is empty. Write
> it as a list: the code accepts a bare `pages: live`, but `pages: [live]` is
> the form to use.

Params on the Reflex server entry:

| Param | Default | Effect |
|---|---|---|
| `pages` | `[live, action]` | See above. |
| `limit_vis` | — | Only these server keys contribute panels (`/live`, `/action`, `/control`). |
| `poll_interval` | `5` | Operator page poll cadence in seconds. A value that is not a positive number falls back to `5`. |
| `plate_api` | — | `HTEPlateAPI` is the only accepted value. `/operator` reads this server's own value. `/composition` and the spectra pages use the first server in the config that declares one. |
| `retire` | `False` | Literal `true` enables `/retire`. The page deletes metadata-API rows and moves run directories, so turn it on only where intended. |
| `retire_sources_root` | — | Folder of converter sources. `/retire` refuses a sequence that has a converter job still in progress under this folder. |
| `seqspec_parser_path` / `seqspec_folder_path` / `parser_kwargs` | — | Spec-sequence tab of `/operator`. The two paths resolve relative to the repo root when not absolute. See [`group: operator`](#group-operator). |

## Ports

Beyond the declared `port`, servers claim ports implicitly. Only the first is
checked:

| Consumer | Port | Checked by `validateConfig`? |
|---|---|---|
| The server itself | `port` | yes |
| Reflex backend | `port + 1` | yes — `reserved_addresses` returns both |
| ZMQ RPC (every FastAPI server) | `port + 10000` | **no** |

`validateConfig` rejects duplicate `host:port` pairs across the group. It does
not model the RPC offset, so two servers 10000 apart pass validation and then
collide at runtime: the second binds, fails, and falls back to the `0.0.0.0`
wildcard with a warning — which listens on *every* interface. Keep station
ports well inside a 10000-wide band.

The RPC socket binds to the configured `host`. When that name does not resolve
to a locally assigned address (a FQDN whose DNS points elsewhere, for
instance), the bind fails where uvicorn's would have succeeded, and the same
wildcard fallback applies.

## Group conventions for `params:`

`params` is free-form and forwarded to the server's `makeApp`, but each group
has keys the shared framework code reads.

### `group: orchestrator`

| Param | Default | Effect |
|---|---|---|
| `heartbeat_interval` | `10.0` | Seconds between status pings to action servers. |
| `ignore_heartbeats` | — | Server keys whose missed heartbeats are not treated as errors. |
| `verify_plates` | `True` | Require plate verification against the plate API. |
| `enable_op` | — | **Deprecated and ignored.** The operator is a separate `group: operator` server now. |

Queue restore is a server-level key, not a param: `restore_queues_on_startup:
true` makes this orchestrator import `STATES/queues.pck` on every start. The
`--restore` CLI flag sets the same thing for one launch. A restored pickle is
archived so it is not replayed twice.

### `group: operator`

| Param | Default | Effect |
|---|---|---|
| `orch_key` | `ORCH` | Which orchestrator in this config to attach to. |
| `poll_interval` | | Seconds between queue/status polls. |
| `plate_api` | — | Named plate API backend. Only `HTEPlateAPI` is accepted; another name is ignored with a warning. |
| `doc_name` | `<key> Bokeh App` | Bokeh document title. |
| `seqspec_folder_path` | — | Folder of sequence-spec files. |
| `seqspec_parser_path` | — | Path to the deployment's `SpecParser` module. |

> **`seqspec_*` must be on the operator server, not the orchestrator.** The
> Bokeh operator and the Reflex `/operator` page each read these keys from
> their **own** server entry's `params`. Under `ORCH.params` they have no
> effect. The Reflex spec tab then reports that no spec parser is configured,
> and the Bokeh spec list stays empty with no message.

### `group: visualizer`

| Param | Default | Effect |
|---|---|---|
| `doc_name` | `<key> Bokeh App` | Bokeh document title. |
| `launch_browser` | `False` | Open a browser tab when the app starts. |
| `max_points` | varies | Trailing-window size for plots (`50000` in the data browser). |
| `limit_vis` | — | Only these server keys are visualized. Bokeh and Reflex. Write a list: Bokeh tests a bare string as a substring. |
| `pages`, `retire`, … | — | Reflex only. See [Reflex UI pages](#reflex-ui-pages). |

## Validation rules

`validateConfig` aborts the launch when:

1. `servers` is missing;
2. any server lacks `host`, `port`, or `group`;
3. `host` is not a string, `port` is not an int, or `group` is not a string;
4. a server declares more than one of `fast` / `bokeh` / `reflex`, or declares
   one that is not a string;
5. two servers claim the same `host:port` (counting a Reflex server's
   `port + 1`);
6. **more than one server declares `params.positions`.** Sample-archive state
   is a single-owner resource; two owners race on the shared state JSON.

Per-server module existence is *not* checked — that block is commented out, so
a mistyped `fast:` value fails later, inside the launcher, as an import error.

## Hot reload

```yaml
hot_reload:
  enabled: true      # default
  poll_seconds: 30   # default
```

The watcher polls the parent repo and each nested deployment repo; on a pulled
commit it restarts the idle servers whose loaded code changed. Orchestrators
restart only when idle, and come back with `--restore`.

Precedence: `--no-hot-reload` beats `--hot-reload` beats the config key.
`CTRL-t` toggles the watcher at runtime.

## Worked example

```yaml
dummy: true
simulation: true
show_debug: true
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
backend, and, implicitly, `18001`/`18002` for RPC.

## Checklist for a new station config

- [ ] `root` is absolute, not `~`-relative, and not shared with another group
- [ ] `dummy` is present (a missing key is a `KeyError` at launch, not a default)
- [ ] `run_type` set — it labels every record the station produces
- [ ] every server has `host`, `port` (an int), `group`
- [ ] exactly one code key per managed server; omit it deliberately for
      externally managed ones
- [ ] no two servers within 10000 of each other's port
- [ ] a Reflex server's `port + 1` is free
- [ ] every action server that should be visualized names `action_vis` or
      `live_vis`
- [ ] at most one server declares `params.positions`
- [ ] operator servers name the right `orch_key`, and carry their own
      `seqspec_*` params
- [ ] finish hooks use `prefinish_*` / `postfinish_hooks`, not the deprecated
      `*_postprocess_libs` lists
- [ ] a `postfinish_hooks` block still lists `s3_upload` at every level that
      should upload
- [ ] the syncer server is keyed `SYNC`
- [ ] Reflex `pages` is a list; `retire: true` only where retiring is intended
- [ ] if the file lives outside `helao/deploy/*/configs/`, every server carries
      an explicit `deployment:`
- [ ] `python launch.py <prefix>` reaches the banner — that proves validation
      and the pre-launch unit-test gate both passed
