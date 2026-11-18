# gpsim

Simulated Gaussian-process acquisition server (`gpsim_server`, driver `GPSim`, model code in `gp_backend.py`): proposes and "measures" points from the stored OER dataset. `bokeh/gpsim_live_vis.py` and `reflex/gpsim_panel.py` show the state.

## Vendor software
No vendor software beyond the env files. `gpytorch` and `pytorch-cpu` come from this folder's `environment.yml`.

## Params
Host-level keys every server accepts: see `docs/config-schema.md` ("Group conventions for `params:`").

### `gpsim_server` (`fast:` value)
| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `random_seed` | yes | int | none | Seed of the driver's NumPy random generator. `KeyError` at startup if absent. The `initialize_global` action has its own `random_seed` action param (default `9999`); that is a separate value. | `helao/deploy/test/servers/gpsim/gpsim_driver.py:80` |
| `minimize` | no | bool | `True` | `True`: targets are `-eta`, so the search minimizes overpotential. `False`: targets are `+eta`. No existing config sets it. | `helao/deploy/test/servers/gpsim/gpsim_driver.py:98` |

Example (from `demo0.yml`):
```yaml
params:
  random_seed: 9999
```

The panels (Bokeh and Reflex) read no params.

## Outputs

Actions here write through the framework default data connection: one JSON object per line, file `<action_abbr>-<orch_submit_order>.<action_order>.<action_retry>.<action_split>__<n>.jsonl` plus `.meta.json` header (`helao/hexagon/adapters/native/data_file.py:172`, `:288`). Columns are the keys of the first message queued (`helao/hexagon/adapters/native/data_stream.py:338`). Every row below is one "progress" dict; its builders are in `helao/deploy/test/servers/gpsim/gpsim_driver.py`.

Progress dict (`acquire_point` branch with no `init_point`):

| field | type | structure | unit | meaning | written at |
|---|---|---|---|---|---|
| `expected_improvement` | float | scalar per row | unknown (dynamic) | EI of the chosen composition | `helao/deploy/test/servers/gpsim/gpsim_driver.py:278` |
| `feature` | list[int] | list | at. % (as stored) | composition vector of the chosen point | `helao/deploy/test/servers/gpsim/gpsim_driver.py:279` |
| `total_plate_mae` | float | scalar per row | unknown (dynamic) | mean absolute error of the model over the whole plate | `helao/deploy/test/servers/gpsim/gpsim_driver.py:280` |
| `plate_step` | int | scalar per row | none | number of points acquired on this plate before this one | `helao/deploy/test/servers/gpsim/gpsim_driver.py:281` |
| `global_step` | int | scalar per row | none | acquisitions across all plates so far | `helao/deploy/test/servers/gpsim/gpsim_driver.py:282` |

### `initialize_global` (action)

No data files or action results.

### `initialize_plate` (action)

No data files or action results. It also publishes live status through `put_lbuf` (see "Live data" below).

### `get_progress` (action)

Writes the plate's stored progress dict as one row and as underscore-prefixed `action_params` keys; writer `helao/deploy/test/servers/gpsim/gpsim_server.py:92-93`.

Data file `<action_abbr>-*.jsonl` (+ `.meta.json`), one row: the progress dict above (`gpsim_server.py:93`). The stored dict is `{}` until an `acquire_point` has run for the plate; the row is then `{}` and no `_` keys are set.

Action results (in `-act.json`):

| key | in | type | structure | meaning | set at |
|---|---|---|---|---|---|
| `_expected_improvement`, `_feature`, `_total_plate_mae`, `_plate_step`, `_global_step` | `action_params` | as the progress dict | as the progress dict | `_` + each progress field | `helao/deploy/test/servers/gpsim/gpsim_server.py:92` |

### `acquire_point` (action)

Writes the progress dict of the chosen point as one row; writer `helao/deploy/test/servers/gpsim/gpsim_server.py:112`.

Data file `<action_abbr>-*.jsonl` (+ `.meta.json`), one row: the progress dict above.

Action results (in `-act.json`):

| key | in | type | structure | meaning | set at |
|---|---|---|---|---|---|
| `_feature` | `action_params` | list[int] | list | composition vector chosen | `helao/deploy/test/servers/gpsim/gpsim_server.py:113` |

### `update_model` (action)

Refits the surrogate via `GPSimExec` (`helao/deploy/test/servers/gpsim/gpsim_server.py:128`); `action_abbr` is `GPSIM` (`:127`). Its `_post_exec` queues the plate's stored progress dict as one row (`helao/deploy/test/servers/gpsim/gpsim_driver.py:595-599`), data file `GPSIM-*.jsonl` (+ `.meta.json`) with the progress dict fields above. An empty dict queues no row (`helao/hexagon/app/executor_runner.py:158`).

Action results (in `-act.json`):

| key | in | type | structure | meaning | set at |
|---|---|---|---|---|---|
| `orch_str` | `action_params` | str | scalar | `"<orch_key> <orch_host>:<orch_port>"` of the requesting orchestrator | `helao/deploy/test/servers/gpsim/gpsim_server.py:124` |

### `check_condition` (action)

Evaluates the stop condition and, if unmet, inserts a repeat experiment; writes one row; writer `helao/deploy/test/servers/gpsim/gpsim_server.py:151`.

Data file `<action_abbr>-*.jsonl` (+ `.meta.json`), one row: the progress dict above plus

| field | type | structure | unit | meaning | written at |
|---|---|---|---|---|---|
| `max_prediction_stdev` | float | scalar per row | unknown (dynamic) | maximum predictive variance over the available points | `helao/deploy/test/servers/gpsim/gpsim_driver.py:551` |

The progress dict it extends is the stored one, mutated in place (`gpsim_driver.py:548-555`).

API writes:

| endpoint | payload field | type | structure | meaning | sent at |
|---|---|---|---|---|---|
| orchestrator `insert_experiment` (private) | `idx` | int | scalar | insert position, always `0` | `helao/deploy/test/servers/gpsim/gpsim_driver.py:537` |
| orchestrator `insert_experiment` (private) | `experiment` | dict | dict | `Experiment(experiment_name, experiment_params, **kwargs).clean_dict()` from the action's `repeat_experiment_*` params | `helao/deploy/test/servers/gpsim/gpsim_driver.py:525`, `:539` |

Sent only when the stop condition is unmet and the plate is not exhausted (`:520-523`).

### Live data (status/ws stream)

Published with `put_lbuf`, never written to a file. Each key is stamped `(value, epoch)` (`helao/hexagon/app/action_host.py:403`).

| field | type | structure | unit | meaning | written at |
|---|---|---|---|---|---|
| `status` | str | scalar per poll | none | "<orch> was advised to measure composition <compstr>" (`acquire_point`) | `helao/deploy/test/servers/gpsim/gpsim_driver.py:301` |
| `plate_id` | list[int] | list of one | none | plate refit | `helao/deploy/test/servers/gpsim/gpsim_driver.py:366` |
| `step` | list[int] | list of one | none | `plate_step - 1` | `helao/deploy/test/servers/gpsim/gpsim_driver.py:367` |
| `frac_acquired` | list[float] | list of one | fraction | acquired (plate + global) over plate size | `helao/deploy/test/servers/gpsim/gpsim_driver.py:368` |
| `last_acquisition` | list[str] | list of one | none | composition string | `helao/deploy/test/servers/gpsim/gpsim_driver.py:381` |
| `pred_avail` | list[list[float]] | list of one | unknown (dynamic) | model prediction over available points, sign-flipped | `helao/deploy/test/servers/gpsim/gpsim_driver.py:382` |
| `gt_acquired` | list[list[float]] | list of one | unknown (dynamic) | ground-truth targets of acquired points, sign-flipped | `helao/deploy/test/servers/gpsim/gpsim_driver.py:383` |
| `orchestrator` | list[str] | list of one | none | requesting orchestrator label | `helao/deploy/test/servers/gpsim/gpsim_driver.py:384` |
| `status` | list[str] | list of one | none | "<compstr> was acquired on <orch>" (`fit_model`) | `helao/deploy/test/servers/gpsim/gpsim_driver.py:385` |

## Notes

- `initialize_plate` and `get_progress` call the `async def fit_model` without `await` (`helao/deploy/test/servers/gpsim/gpsim_server.py:75`, `:90`), so the refit never runs there; `get_progress` therefore stays an empty dict when no `acquire_point` has stored progress (`fit_model` does not set `progress`, `helao/deploy/test/servers/gpsim/gpsim_driver.py:319-430`).
