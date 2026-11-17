# /runners page — design

Date: 2026-11-17
Status: draft, awaiting review
Scope: sub-project 2 of 2. Sub-project 1 (runners on /group,
`2026-11-16-microorch-group-feed-design.md`) is merged; a launched runner shows
up on /group through that feed with no further work.

## Goal

From a Reflex page, an operator picks a runner script from the group's
deployment, fills in its parameters, checks the action servers it needs, launches
it, watches it on /group, and stops it.

Success: on `goldenreflex`, /runners lists the `test` deployment's runners; for
`simulatews` the requirement checklist shows ORCH `wait` and SIM `acquire_data`
green; Launch starts it, it appears on /group as a peer; Stop ends it after its
in-flight action and it deregisters; launching it again with SIM down is blocked until "launch
anyway" is ticked; adding a new runner file, editing a runner's default and
deleting a runner file each show up after Refresh, without restarting the group.

## Decisions

| # | Decision | Reason |
|---|----------|--------|
| D1 | The page offers runner scripts, not sequences. | User choice. |
| D2 | Catalog = `runners/*.py` in the config's own deployment that define `run`. | User choice: no list to maintain, scoped by deployment. |
| D3 | Runners execute as subprocesses of the Reflex server. | A crash or blocking call in runner code cannot freeze or kill the UI. |
| D4 | Stop = SIGTERM: stop dispatching, let the in-flight action finish, finish records, deregister. A second press ("Force kill") sends SIGKILL; there is no automatic SIGKILL, because a long in-flight action must not be cut. | User choice. E-stop stays the way to halt hardware immediately. |
| D5 | Several runners may run at once, alongside the orchestrator; the page warns on server overlap and never blocks for it. | User choice. |
| D6 | Requirements are declared by the runner (`REQUIRES`); undeclared runners get a static-scan hint. | Server/action choice is runtime code; inference alone misses parameter-built calls. |
| D7 | A failed requirement check blocks Launch; a "launch anyway" checkbox overrides. Busy servers only warn; inferred requirements only warn. | User choice. |
| D8 | The page never imports runner modules. It learns each runner's signature, docstring and requirements from a `--describe` subprocess, and a Refresh button rebuilds the catalog. | Runners are a development tool: files are added, edited and deleted while the UI runs. A fresh subprocess always sees the current file (no `sys.modules` cache) and keeps runner top-level code out of the UI process. |

## Runner contract

A runner is a module `helao/deploy/<deployment>/runners/<name>.py` that defines:

```python
REQUIRES = {"ORCH": ["wait"], "SIM": ["acquire_data"]}   # optional

async def run(orch: MicroOrch, wait_time: float = 3.0, cycles: int = 2) -> None:
    """One-line summary shown on the page.

    Longer description, also shown.
    """
```

- `run` is an `async def`. Its first parameter is annotated `MicroOrch`; every
  other parameter is positional with a default and preferably an annotation.
  This is the experiment/sequence convention, so
  `helao/ui/shared/operator/param_forms.py` builds the form unchanged, with
  `filter_type=MicroOrch` hiding `orch`.
- `REQUIRES` maps server key → list of action names. It is optional (D6).
- A module without a callable `run` is not a runner and is not listed.
- The runner gets a started MicroOrch built from the group config; it never builds
  its own and never hard-codes `WORLD_CFG`, `ROOT` or ports.

The three existing runners in `helao/deploy/test/runners/` (`oersim_runner`,
`simulatews_runner`, `test_runner`) migrate: module constants become `run`
parameters with the same defaults, `WORLD_CFG`/`ROOT` and the MicroOrch
construction go, each gains `REQUIRES`, and `main()` is replaced by the
launcher (below). `test_runner`'s two scenarios become one `run` with a
`scenario: str = "both"` parameter.

## Launcher

New module `helao/core/runners/launch.py`, run as
`python -m helao.core.runners.launch <config_prefix> <module> [--key K] [--params JSON]`.

1. `read_config(config_prefix)` gives `world_cfg`; `<module>` is a dotted path
   (`helao.deploy.test.runners.simulatews_runner`).
2. Key: `--key`, else the module's final name upper-cased without a trailing
   `_RUNNER` (`SIMULATEWS`). The key must not equal a config server key; exit 2
   with a message if it does.
3. Builds `MicroOrch(server_key=key, host=<host of the config's reflex server,
   else 127.0.0.1>, port=<free port whose derived RPC port is also free>,
   world_cfg=world_cfg)`; the feed targets come from the config's `reflex:`
   entries as in sub-project 1.
4. Validates `--params` against `run`'s signature: unknown names exit 2; values
   are coerced with the annotation when one is given (int/float/bool/str), else
   passed as parsed JSON.
5. `async with orch: await module.run(orch, **params)`.
6. SIGTERM (and SIGINT) request a cooperative stop; the `run` task is not
   cancelled (cancelling it would abandon the wait on the in-flight action and
   leave its experiment record unfinished). New on MicroOrch:
   `request_stop()` sets a flag; `dispatch_action` raises `RunnerStopped`
   (new exception in `micro_orch.py`) instead of dispatching while the flag is
   set. Actions already dispatched are still awaited to their terminal status.
   `run_experiment` / `run_sequence` catch `RunnerStopped`, finish the current
   experiment (and sequence) with status `aborted` through the normal
   `_finish_experiment` / `_finish_sequence` path, and re-raise. The launcher
   treats `RunnerStopped` as a clean stop: `orch.stop()` deregisters, exit 0.
   A second SIGTERM/SIGINT while stopping cancels the `run` task outright
   (records of the interrupted experiment stay unfinished), then exits 130.
7. An exception from `run` is logged with its traceback (module LOGGER) and the
   process exits 1.
8. `arm_parent_death_signal()` (helao/helpers/parent_death.py) is called first, so
   a runner dies with the Reflex server that spawned it. Run by hand from a
   terminal it has no such parent and behaves as a normal script.

Running a migrated runner by hand: `python -m helao.core.runners.launch goldenreflex
helao.deploy.test.runners.simulatews_runner`.

**Describe mode:** `python -m helao.core.runners.launch --describe <module>`
imports the module (no config, no MicroOrch, no network), prints one JSON object
to stdout and exits 0:
`{"module", "doc", "args", "defaults", "argtypes", "requires", "inferred"}`.
`args`/`defaults`/`argtypes` follow `param_forms`' item fields (`orch` excluded;
annotations as type-name strings), `requires` is `REQUIRES` or null, `inferred`
is the static scan below. A module that fails to import, or has no async
`run(orch, ...)`, prints `{"module", "error": "<one-line reason>"}` and exits 1.

## Requirement check

`helao/ui/reflex/runner_requirements.py` (pure functions, no Reflex):

- `declared` requirements come from the describe output's `requires`.
- `inferred(source: str) -> dict` (called by `--describe`): AST scan of the module source for calls whose
  first two arguments are string literals and whose callee is named `_act` or
  `Action`-building helpers (`_act`, `make_action`), plus `Action(...)` calls with
  literal `action_name=` and `action_server=MachineModel(server_name=...)`.
  Anything non-literal is skipped. Result is labelled "inferred, may be
  incomplete".
- `check(requires, world_cfg, endpoints_by_server, status_by_server) -> list[row]`,
  one row per (server, action): `in_config`, `reachable`, `has_endpoint`,
  `estopped`, `busy` and a verdict `ok | warn | fail`. A row fails when the server
  is not in the config, is unreachable, lacks the endpoint, or is E-stopped; it
  warns when busy, or when the requirement is only inferred and would otherwise
  fail.

The page gathers `endpoints_by_server` with `POST /endpoints` (route records whose
`path` is `/<KEY>/<action>`) and `status_by_server` with `POST /get_status`, both
with `timeout=5, retries=1`, in parallel, when a runner is selected and on a
Re-check button — never on a timer.

## Page

New module `helao/ui/reflex/runners.py`, route `/runners`, added in `app.py`
beside /group.

- **Catalog:** the config's deployment is the one holding its config file
  (`helao/deploy/<deployment>/configs/`). Every `runners/*.py` there (not
  `__init__.py`) is described with the launcher's `--describe` mode, one
  subprocess per file, in parallel, 10 s timeout each. The catalog is built on
  page mount and rebuilt by a **Refresh** button; never on a timer. Each entry
  shows the docstring summary and the file's modification time. A file whose
  describe fails is listed greyed out with its error and cannot be launched; a
  deleted file disappears; an edited file shows its new parameters and
  requirements. Refresh does not touch running processes. The catalog is
  process-wide (one per Reflex server), so every open tab sees the same list.
- **Form:** the selected runner's parameters, rendered from the describe output
  with the operator page's field builders (the describe JSON has the same fields
  as a `param_forms` item); values persist per runner in the same `param_store`
  the operator uses (`kind="runner"`). After a Refresh, stored values for
  parameters the runner no longer has are dropped, and new parameters show their
  defaults.
- **Requirements:** the checklist above. Launch is disabled while any row
  fails, unless "launch anyway" is ticked.
- **Launch:** key field (prefilled as the launcher's default). Refused if the key
  is already running from this page or registered on /group. Spawns the launcher
  with `asyncio.create_subprocess_exec` using the Reflex server's own interpreter
  (`sys.executable`), `PYTHONPATH` and the group's config prefix; stdout+stderr
  go to `<root>/LOGS/runner_<KEY>_<YYYYMMDD-HHMMSS>.log`.
- **Process table:** one row per runner launched by this Reflex process: key,
  module, PID, started, state (`running` / `stopping` / `exited <rc>`), Stop
  button, a link to `/group` with that runner selected, and the log file path.
  Exited rows stay until dismissed. Process state lives in a module-level
  registry (not Reflex state), polled by the page tick.
- **Stop:** SIGTERM, state `stopping`; the button becomes **Force kill**, which
  sends SIGKILL and sets state `killed`. Kill only by PID.
- **Overlap warning:** from /group's feeds, the servers each running runner and
  each orchestrator are busy on; a server busy for two of them is listed with
  both names. Never blocks.

## Risks

- The launcher's host default is the Reflex server's host; action servers must be
  able to reach it for status callbacks. A group spread over hosts where the UI
  host is not reachable from the action servers needs `--host`.
- Runner code runs with the Reflex server's user and environment.
- Static inference can be wrong in both directions; it only ever warns.
- A runner that blocks its own event loop cannot be stopped gracefully; Force
  kill still ends it, without deregistering (the /group entry goes stale after
  5 s and is swept as usual) and without finishing its records.
- An interrupted experiment/sequence is recorded `aborted`, which /group draws
  in the error colour; that is deliberate (the run did not complete).
- Parent-death only works on Linux (as for every helao server).

## Testing

Unit:
- `inferred()` on the three migrated runners and on synthetic sources (literal,
  variable, `Action(...)` forms).
- `check()` verdicts for each failure kind, busy, and inferred-only.
- `--describe` (real subprocess): a valid runner gives the documented JSON; a
  non-runner module and a module that fails to import give `error` and exit 1.
- Catalog discovery and Refresh: a temp deployment with a runner, a non-runner
  module, and a module that fails to import; then add a file, edit a runner's
  default, and delete a file — after Refresh the catalog shows all three changes,
  and stored form values for a removed parameter are dropped.
- MicroOrch cooperative stop (with the fake action server of
  `unit_test_micro_orch.py`): `request_stop()` mid-experiment lets the
  dispatched action finish, dispatches nothing more, writes the experiment record
  with status `aborted`, and raises `RunnerStopped`.
- Launcher: params validation and coercion, key derivation and the config-key
  clash, and a real subprocess running a fake runner — SIGTERM exits 0 and the
  fake saw `RunnerStopped`; a second SIGTERM exits 130; an exception exits 1.
- Page process registry: launch refuses a duplicate key; Stop sends SIGTERM and
  Force kill SIGKILL to a fake process that ignores SIGTERM.
- The three migrated runners import and expose `run` with the old defaults.

Integration (headless, as in sub-project 1): the Success scenario on
`goldenreflex`, including the blocked launch with SIM stopped.

## Out of scope

- Sequences or experiments as page-launchable items (D1).
- Remote hosts: runners always run on the Reflex server's host.
- Scheduling, queues, or chaining runners.
