# HELAO config schema

A config file defines one **orchestration group**: the set of servers
`launch.py` starts together, plus the on-disk root they all write to. This
document covers the keys that are shared by every station and every server.
Driver-specific `params:` (COM ports, channel maps, device tables) are out of
scope — they are documented by the action server that reads them.

Two things read a config, and they disagree about what is required:

| Reader | When | Enforcement |
|---|---|---|
| `validateConfig` (`launch.py:846`) | at launch, before any server starts | aborts the whole group |
| `HelaoConfig` (`helao/helpers/config_loader.py:248`) | inside each server, at `Base.__init__` | raises `ValueError` in that server only |

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
> `launch.py` reads `config["dummy"]` unsubscripted at three points while
> printing the banner (`launch.py:1446`), so a config without it dies with a
> `KeyError` before any server starts. `HelaoConfig` defaults it to `True`,
> which never gets the chance to apply. All 37 tracked configs set it.

### Optional

| Key | Type | Default | Effect |
|---|---|---|---|
| `simulation` | bool | `True` (schema) / `False` (runtime readers) | Stamped onto every action, experiment and sequence record. Most action servers also select simulated drivers on it. |
| `experiment_libraries` | list[str] | — | Modules whose `EXPERIMENTS` list the orchestrator publishes. |
| `sequence_libraries` | list[str] | — | Modules whose `SEQUENCES` list the orchestrator publishes. |
| `experiment_params` | dict | — | Defaults merged into experiments at runtime. |
| `sequence_params` | dict | — | Defaults merged into sequences at runtime. |
| `experiment_path` / `sequence_path` | str | `helao/deploy/<deployment>/{experiments,sequences}` | Overrides where library modules are looked up. Undeclared in `HelaoConfig`. |
| `show_debug` | bool | `False` | Console handler at DEBUG instead of INFO. File logs are unaffected. |
| `log_level` | int | `20` | Launcher and Bokeh/Reflex launcher log level. A server-level `log_level` overrides it. |
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
  RUNS_ACTIVE/    run trees for in-flight sequences
  LOGS/           per-server rotating text logs
  STATES/         pid pickles, queue exports, Bokeh module snapshots
  DATABASE/
  USER_CONFIG/EXP, USER_CONFIG/SEQ
  ANALYSES/
  PROCESSES/
  FAULTS/         asyncio hang-inspection dumps (created on first hang)
```

On startup each server zips and removes any leftover `*.txt` under
`LOGS/<server_name>/`, naming the archive from the first timestamp inside the
log. `RUNS_FINISHED` and `RUNS_SYNCED` are created by the syncer, not here.

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
| `log_level` | int | Bokeh and Reflex launchers. Falls back to the top-level `log_level`, then `20`. |
| `regular_update` | bool | `Base` / `Orch`: start a periodic status broadcast. |
| `regular_update_delay` | float | Seconds between those broadcasts. Default `10`. |
| `hlo_postprocess_libs` | list[str] | `Base`: `HloPostProcessor` modules run over each `.hlo` file. |
| `action_vis` / `live_vis` | str | Names the visualizer/panel module for this server. See below. |
| `verbose` | bool | **Nothing.** See the warning below. |

Two more are orchestrator-only but sit at the server level rather than under
`params:` — `exp_postprocess_libs` and `seq_postprocess_libs`, `MetaProcessor`
modules run when an experiment or sequence finishes.

> **`verbose:` is declared but never read.** It appears in `ServerConfig` with
> the docstring "Enables debug-level logging on the server" and is set on 45
> servers across the tracked configs, but no code anywhere consumes it. Use
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

The value is a bare module name resolved across deployments (configured
deployment first, then `hte`, then the rest alphabetically). The same name
serves both UI stacks — `servers/visualizer/<name>.py` for Bokeh,
`servers/reflex/<name>.py` for Reflex — so a station gains Reflex panels by
adding a `reflex:` server and changing nothing else.

**A server with no `action_vis`/`live_vis` key gets no visualization at all**,
in either stack. This is the usual cause of an empty visualizer page.

For Reflex only, the key chooses the *page* while the panel module's `WS_PATH`
chooses the *socket*; a panel declared under `live_vis` may still read
`ws_data`.

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
| `seqspec_folder_path` | — | Folder of sequence-spec files, read by both operator UIs. |
| `seqspec_parser_path` | — | Path to the deployment's `SpecParser` module. |
| `enable_op` | — | **Deprecated and ignored.** The operator is a separate `group: operator` server now. |

`seqspec_*` live on the *orchestrator* even though the *operator* reads them.

Queue restore is a server-level key, not a param: `restore_queues_on_startup:
true` makes this orchestrator import `STATES/queues.pck` on every start. The
`--restore` CLI flag sets the same thing for one launch. A restored pickle is
archived so it is not replayed twice.

### `group: operator`

| Param | Default | Effect |
|---|---|---|
| `orch_key` | `ORCH` | Which orchestrator in this config to attach to. |
| `poll_interval` | | Seconds between queue/status polls. |
| `plate_api` | — | Named plate API backend. |
| `doc_name` | `<key> Bokeh App` | Bokeh document title. |

### `group: visualizer`

| Param | Default | Effect |
|---|---|---|
| `doc_name` | `<key> Bokeh App` | Bokeh document title. |
| `launch_browser` | `False` | Open a browser tab when the app starts. |
| `max_points` | varies | Trailing-window size for plots. |
| `pages` | — | Reflex only: which pages to serve (`live`, `action`, `operator`, `browser`). |

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
    exp_postprocess_libs:
      - append_params
    seq_postprocess_libs:
      - append_params

  SIM:
    host: 127.0.0.1
    port: 8002
    group: action
    fast: ws_simulator
    live_vis: wssim_live_vis          # names the panel; without it, no plots
    params: {}
    hlo_postprocess_libs:
      - hlo_to_csv

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

Ports here occupy `8001`/`8002` and, implicitly, `18001`/`18002` for RPC.

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
- [ ] operator servers name the right `orch_key`
- [ ] if the file lives outside `helao/deploy/*/configs/`, every server carries
      an explicit `deployment:`
- [ ] `python launch.py <prefix>` reaches the banner — that proves validation
      and the pre-launch unit-test gate both passed
