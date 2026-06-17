# MicroOrch example runners (`test` deployment)

Standalone scripts that reproduce the orchestrator-driven libraries under
`helao/deploy/test/` using
[`MicroOrch`](../../../core/runners/micro_orch.py) instead of the full
orchestrator service. They show how to drive action servers, run experiments
and sequences, hand off parameters, read finished data back, and archive
artifacts — all from a plain Python script with no `Orch`/FastAPI/Bokeh stack.

| Script | Mirrors | Needs action servers? |
|--------|---------|------------------------|
| `oersim_runner.py` | `OERSIM_seq` / `OERSIM_exp` (demo0) | **Yes** — `CPSIM`, `GPSIM` |
| `simulatews_runner.py` | `simulatews_exp.SIM_websocket_data` (test.yml) | **Yes** — `SIM` |
| `test_runner.py` | `TEST_seq` / `TEST_exp` | **No** (orchestrator-internal only) |

## How MicroOrch maps the orchestrator

MicroOrch is an in-process orchestrator replacement: it dispatches actions to
action servers over RPC but hosts **no** action endpoints and keeps **no**
sequence/experiment queue. Two consequences shape these examples:

- **Orchestrator-internal actions have no RPC target.** `ORCH/wait`,
  `ORCH/add_global_param`, and `ORCH/conditional_stop` are provided by the
  orchestrator itself, so they are expressed directly in Python:
  `wait -> asyncio.sleep`, `add_global_param -> orch.global_params[...] = ...`,
  `conditional_stop -> read orch.global_params and break`.
- **Self-requeue becomes a Python loop.** The OER active-learning loop normally
  self-requeues via `GPSIM/check_condition -> Orch/insert_experiment`. MicroOrch
  has no queue, so the script itself loops (`oersim_runner.py`).

Cross-action parameter hand-off is unchanged: `to_global_params` /
`from_global_act_params` flow through `orch.global_params`, which persists across
`run_experiment` calls on the `MicroOrch` instance.

## Shared `root` requirement

MicroOrch reads finished artifacts (yml + data) off the local filesystem via a
loader, so it must use the **same `root`** as the action servers it talks to.
The demo configs use `root: C:/INST_hlo`. Override per-script with the
`HELAO_ROOT` environment variable to match your servers' configured root.

## Running

`test_runner.py` needs nothing extra:

```bash
conda run -n helao python -m helao.deploy.test.runners.test_runner
```

`oersim_runner.py` and `simulatews_runner.py` need their action servers up.
Launch the matching group first (its `ORCH` and visualizers are simply unused —
MicroOrch talks straight to the action servers):

```bash
# OER simulation: brings up CPSIM:8002, GPSIM:8003
./helao.sh demo0
conda run -n helao python -m helao.deploy.test.runners.oersim_runner

# websocket simulator: brings up SIM:8002
./helao.sh test
conda run -n helao python -m helao.deploy.test.runners.simulatews_runner
```

Each runner ends by calling `orch.zip_runs(...)`, writing a `.zip` of every
artifact it produced (preserving the directory structure relative to
`RUNS_FINISHED`) that can be re-opened with
`helao.core.drivers.data.loaders.localfs.LocalLoader`.

## Adapting

- Point `WORLD_CFG["servers"]` at wherever your action servers actually listen.
- Tune the loop sizes / wait times via the constants at the top of each script.
- To read an action's data after a run, the returned objects are loader-backed
  (`HelaoAction` / `HelaoExperiment` / `HelaoSequence`): e.g. `act.hlo` returns
  `(meta, data)` for the primary HLO file.
