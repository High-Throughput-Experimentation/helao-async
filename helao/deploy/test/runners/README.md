# MicroOrch example runners (`test` deployment)

Standalone scripts that reproduce the orchestrator-driven libraries under
`helao/deploy/test/` using
[`MicroOrch`](../../../core/runners/micro_orch.py) instead of the full
orchestrator service. They show how to drive action servers, hand off
parameters between actions, read finished data back, and archive artifacts —
all from a plain Python script with no `Orch` queue/operator stack.

| Script | Mirrors | Action servers used |
|--------|---------|---------------------|
| `oersim_runner.py` | `OERSIM_seq` / `OERSIM_exp` (demo0) | `CPSIM`, `GPSIM` |
| `simulatews_runner.py` | `simulatews_exp.SIM_websocket_data` (test.yml) | `ORCH` (wait), `SIM` |
| `test_runner.py` | `TEST_seq` / `TEST_exp` | `ORCH` (wait / global-param / conditional-stop) |

## `ORCH` is just another action server

`OrchAPI` inherits `BaseAPI`, so the running orchestrator exposes its
orchestrator primitives — `ORCH/wait`, `ORCH/add_global_param`,
`ORCH/conditional_stop` — as ordinary RPC action endpoints. MicroOrch dispatches
to `ORCH` exactly like any driver-backed server; nothing special is required
beyond listing `ORCH` in `WORLD_CFG["servers"]`.

One caveat: `conditional_stop` halts the *orchestrator's own* loop, which
MicroOrch replaces. Dispatching it still exercises the real endpoint, but the
"skip the rest of the sequence" effect is the script's responsibility — the
script reads the same condition and breaks (see `test_runner.py`). Likewise the
OER active-learning self-requeue (`GPSIM/check_condition → Orch/insert_experiment`)
becomes a plain Python loop in `oersim_runner.py`.

## to_global / from_global, script-managed

Under the orchestrator, actions declare `to_global_params` /
`from_global_act_params` and the Orch shuttles values through
`Orch.global_params`. A self-contained MicroOrch script does the same thing
explicitly — the point being that you never need an Orch:

- **to_global** — read the object returned by `run_action` (a loader-backed
  `HelaoAction`), pull the value out of its `action_params`, and store it in a
  plain dict in the script (the runners use a module-level `GLOBALS`). The
  simulator servers stamp their outputs onto `action_params` (e.g.
  `get_loaded_plate → _loaded_plate_id`, `acquire_point → _feature`,
  `add_global_param → <param_name>`), so `action_params` is the source of every
  captured value.
- **from_global** — copy a value out of that dict into the next action's params
  before dispatching it.

`oersim_runner.py` and `test_runner.py` wrap this in two tiny helpers
(`_capture`/`_inject` and `_inject`) that mirror the `to_global_params` /
`from_global_act_params` declarations in the library experiments.

## Shared `root` requirement

MicroOrch reads finished artifacts (yml + data) off the local filesystem via a
loader, so it must use the **same `root`** as the action servers it talks to.
The demo configs use `root: C:/INST_hlo`. Override per-script with the
`HELAO_ROOT` environment variable to match your servers' configured root.

## Running

Launch the matching group first (its operator/visualizer pages are unused —
MicroOrch talks straight to the action servers over RPC):

```bash
# OER simulation: brings up CPSIM:8002, GPSIM:8003
./helao.sh demo0
conda run -n helao python -m helao.deploy.test.runners.oersim_runner

# websocket simulator + ORCH waits: brings up ORCH:8001, SIM:8002
./helao.sh test
conda run -n helao python -m helao.deploy.test.runners.simulatews_runner

# orchestrator-primitive scheduling: needs ORCH:8001
./helao.sh test
conda run -n helao python -m helao.deploy.test.runners.test_runner
```

Each runner ends by calling `orch.zip_runs(...)`, writing a `.zip` of every
artifact it produced (preserving the directory structure relative to
`RUNS_FINISHED`) that can be re-opened with
`helao.core.drivers.data.loaders.localfs.LocalLoader`.

## Adapting

- Point `WORLD_CFG["servers"]` at wherever your action servers (including
  `ORCH`) actually listen.
- Tune loop sizes / wait times via the constants at the top of each script.
- To read an action's data after a run, the returned objects are loader-backed
  (`HelaoAction` / `HelaoExperiment` / `HelaoSequence`): e.g. `act.hlo` returns
  `(meta, data)` for the primary HLO file.
