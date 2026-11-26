# MicroOrch example runners (`test` deployment)

Runner modules that reproduce the orchestrator-driven libraries under
`helao/deploy/test/` using
[`MicroOrch`](../../../core/runners/micro_orch.py) instead of the full
orchestrator service. They show how to drive action servers, hand off
parameters between actions, read finished data back, and archive artifacts,
with no `Orch` queue/operator stack.

Each module follows the runner contract: a module-level `REQUIRES` (the
servers and actions it dispatches) and `async def run(orch, ...)` whose
parameters tune the run. The launcher builds the MicroOrch for you.

| Runner | Mirrors | Action servers used | Launch group first |
|--------|---------|---------------------|--------------------|
| `oersim_runner.py` | `OERSIM_seq` / `OERSIM_exp` | `CPSIM`, `GPSIM` | `demo0` (CPSIM:8002, GPSIM:8003) |
| `simulatews_runner.py` | `simulatews_exp.SIM_websocket_data` | `ORCH` (wait), `SIM` | `test` (ORCH:8001, SIM:8002) |
| `test_runner.py` | `TEST_seq` / `TEST_exp` | `ORCH` (wait / global-param / conditional-stop) | `test` (ORCH:8001) |

## Running

Launch the matching group first (its operator/visualizer pages are unused;
MicroOrch talks straight to the action servers over RPC), then start the
runner from the `/runners` page or the command line:

```bash
./helao.sh demo0
python -m helao.core.runners.launch demo0 helao.deploy.test.runners.oersim_runner

./helao.sh test
python -m helao.core.runners.launch test helao.deploy.test.runners.simulatews_runner
python -m helao.core.runners.launch test helao.deploy.test.runners.test_runner
```

The run root and the server addresses come from the group config
(`<config>`), not from the runner. MicroOrch reads finished artifacts off the
local filesystem, so that root must be the same one the action servers use.

## Tuning

A run is tuned with the `run` parameters, passed as JSON:

```bash
python -m helao.core.runners.launch demo0 helao.deploy.test.runners.oersim_runner \
    --params '{"iterations": 3}'
```

Parameters and defaults: `oersim_runner` `plate_id`, `init_random_points`,
`iterations`; `simulatews_runner` `wait_time`, `data_duration`; `test_runner`
`wait_time`, `cycles`, `samples`, `scenario` (`noblocking`, `conditional` or
`both`, default `both`).

## `ORCH` is just another action server

`OrchHost` subclasses `ActionHost`, so the running orchestrator exposes its
orchestrator primitives (`ORCH/wait`, `ORCH/add_global_param`,
`ORCH/conditional_stop`) as ordinary RPC action endpoints. MicroOrch dispatches
to `ORCH` exactly like any driver-backed server.

One caveat: `conditional_stop` halts the *orchestrator's own* loop, which
MicroOrch replaces. Dispatching it still exercises the real endpoint, but the
"skip the rest of the sequence" effect is the runner's responsibility: it
reads the same condition and returns (see `test_runner.py`). Likewise the
OER active-learning self-requeue (`GPSIM/check_condition -> Orch/insert_experiment`)
becomes a plain Python loop in `oersim_runner.py`.

## to_global / from_global, runner-managed

Under the orchestrator, actions declare `to_global_params` /
`from_global_act_params` and the Orch shuttles values through
`Orch.global_params`. A runner does the same thing explicitly:

- **to_global**: read the object returned by `run_action` (a loader-backed
  `HelaoAction`), pull the value out of its `action_params`, and store it in a
  plain dict (the runners use a module-level `GLOBALS`). The simulator servers
  write their outputs to `action_output` (e.g.
  `get_loaded_plate -> _loaded_plate_id`, `acquire_point -> _feature`,
  `add_global_param -> <param_name>`).
- **from_global**: copy a value out of that dict into the next action's params
  before dispatching it.

`oersim_runner.py` and `test_runner.py` wrap this in small helpers
(`_capture`/`_inject` and `_inject`).

Each runner ends by calling `orch.zip_runs(...)`, writing a `.zip` of every
artifact it produced (relative to `RUNS`) that can be re-opened with
`helao.core.drivers.data.loaders.localfs.LocalLoader`.

## Adapting

- To read an action's data after a run, the returned objects are loader-backed
  (`HelaoAction` / `HelaoExperiment` / `HelaoSequence`): e.g. `act.hlo` returns
  `(meta, data)` for the primary HLO file.
