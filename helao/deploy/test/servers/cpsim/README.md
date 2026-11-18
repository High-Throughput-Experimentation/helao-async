# cpsim

Simulated potentiostat (`cpsim_server`, driver `CPSim`): replays stored OER chronopotentiometry traces from `helao/deploy/test/demos/data/oer13_cps.pzstd`. `bokeh/oersim_vis.py` and `reflex/oersim_panel.py` plot them.

## Vendor software
No vendor software beyond the env files.

## Params
Host-level keys every server accepts: see `docs/config-schema.md` ("Group conventions for `params:`").

### `cpsim_server` (`fast:` value)
| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `plate_id` | yes | int | none | Plate loaded at startup. Must be a key of the dataset, else `KeyError` at startup. `change_plate` switches it later. | `helao/deploy/test/servers/cpsim/cpsim_driver.py:55` |
| `column_aliases` | no | dict `{stored_name: emitted_name}` | `{}` | Renames emitted columns so the simulator can feed a panel written for other hardware. A value that is not a dict is treated as empty. | `helao/deploy/test/servers/cpsim/cpsim_driver.py:60` |

Example (from `htereflex.yml`):
```yaml
params:
  plate_id: 2750
  column_aliases:
    erhe_v: Ewe_V
```

The panels `oersim_vis` (Bokeh and Reflex) read no params.

## Outputs

Every action here writes through the framework default data connection: one row per queued message, one JSON object per line, file `<action_abbr>-<orch_submit_order>.<action_order>.<action_retry>.<action_split>__<n>.jsonl` plus `<same>.meta.json` header (`helao/hexagon/adapters/native/data_file.py:172`, `:288`). The column set is the key set of the first message queued (`helao/hexagon/adapters/native/data_stream.py:338`).

### `measure_cp` (action)

Streams the stored CP trace for `comp_vec` into one data file, header row first then one row per poll; executor `CPSimExec` (`helao/deploy/test/servers/cpsim/cpsim_server.py:60`). `action_abbr` is `CPSIM` (`:58`).

Data file `CPSIM-*.jsonl` (+ `.meta.json`):

| field | type | structure | unit | meaning | written at |
|---|---|---|---|---|---|
| `elements` | list[str] | list[str] | none | first row only; element symbols of the selected composition (`el_str` split on `-`) | `helao/deploy/test/servers/cpsim/cpsim_driver.py:185` |
| `atfracs` | list[float] | list[float] | at. % (as stored) | first row only; fraction of each element; elements are float as shipped in `helao/deploy/test/demos/data/oer13_cps.pzstd` | `helao/deploy/test/servers/cpsim/cpsim_driver.py:185` |
| `t_s` | list[float \| int] | list[float \| int] | s | time since trace start; one slice per poll row, empty in the first row; elements are float or int as shipped in `helao/deploy/test/demos/data/oer13_cps.pzstd` | `helao/deploy/test/servers/cpsim/cpsim_driver.py:206` |
| `erhe_v` | list[float] | list[float] | V vs RHE | working-electrode potential; one slice per poll row, empty in the first row; elements are float as shipped in `helao/deploy/test/demos/data/oer13_cps.pzstd` | `helao/deploy/test/servers/cpsim/cpsim_driver.py:206` |
| `<column>` | unknown (dynamic) | list[unknown (dynamic)] | unknown (dynamic) | any further key of a stored `CP3` dict, one slice per poll row. The shipped dataset has exactly `t_s` and `erhe_v`; another dataset may add keys of unknown type | `helao/deploy/test/servers/cpsim/cpsim_driver.py:188`, `:206` |

Column names are the stored names after the `column_aliases` rename (`helao/deploy/test/servers/cpsim/cpsim_driver.py:206`). The first row (`_exec`, `:185-188`) carries `elements`, `atfracs` and the empty series; poll rows (`_poll`, `:205-217`) carry only the series slices.

Action results (in `-act.json`):

| key | in | type | structure | meaning | set at |
|---|---|---|---|---|---|
| `mean_eta_vrhe` | `action_params` | float | scalar | OER overpotential: mean of `erhe_v` over the last 4 s of the trace minus 1.23 V | `helao/deploy/test/servers/cpsim/cpsim_driver.py:226` |

### `cancel_measure_cp` (action)

No data files or action results.

### `get_loaded_plate` (action)

Writes one row and four underscore-prefixed `action_params` keys; writer `helao/deploy/test/servers/cpsim/cpsim_server.py:100-101`.

Data file `<action_abbr>-*.jsonl` (+ `.meta.json`), one row:

| field | type | structure | unit | meaning | written at |
|---|---|---|---|---|---|
| `loaded_plate_id` | int | scalar per row | none | the startup `plate_id` (never updated by `change_plate`; see Notes) | `helao/deploy/test/servers/cpsim/cpsim_server.py:95` |
| `orch_key` | str \| null | scalar per row | none | first orchestrator-group server key in the config, `null` if none (`helao/hexagon/app/action_host.py:238-250`) | `helao/deploy/test/servers/cpsim/cpsim_server.py:96` |
| `orch_host` | str \| null | scalar per row | none | that orchestrator's host, `null` if none | `helao/deploy/test/servers/cpsim/cpsim_server.py:97` |
| `orch_port` | int \| null | scalar per row | none | that orchestrator's port, `null` if none | `helao/deploy/test/servers/cpsim/cpsim_server.py:98` |

Action results (in `-act.json`):

| key | in | type | structure | meaning | set at |
|---|---|---|---|---|---|
| `_loaded_plate_id` | `action_params` | int | scalar | copy of `loaded_plate_id` (startup plate; see Notes) | `helao/deploy/test/servers/cpsim/cpsim_server.py:100` |
| `_orch_key` | `action_params` | str \| null | scalar | copy of `orch_key`; `null` with no orchestrator | `helao/deploy/test/servers/cpsim/cpsim_server.py:100` |
| `_orch_host` | `action_params` | str \| null | scalar | copy of `orch_host` | `helao/deploy/test/servers/cpsim/cpsim_server.py:100` |
| `_orch_port` | `action_params` | int \| null | scalar | copy of `orch_port` | `helao/deploy/test/servers/cpsim/cpsim_server.py:100` |

### `change_plate` (action)

Writes one row and one `action_params` key; writer `helao/deploy/test/servers/cpsim/cpsim_server.py:114-115`.

Data file `<action_abbr>-*.jsonl` (+ `.meta.json`), one row:

| field | type | structure | unit | meaning | written at |
|---|---|---|---|---|---|
| `loaded_plate_id` | int | scalar per row | none | the startup `plate_id`, not the requested one (see Notes) | `helao/deploy/test/servers/cpsim/cpsim_server.py:115` |

Action results (in `-act.json`):

| key | in | type | structure | meaning | set at |
|---|---|---|---|---|---|
| `_loaded_plate_id` | `action_params` | int | scalar | the startup `plate_id`, not the requested one (see Notes) | `helao/deploy/test/servers/cpsim/cpsim_server.py:114` |

## Notes

- `_poll` emits `v[last_idx:newest_idx]`, a half-open slice, and finishes when `newest_idx` reaches the last index (`helao/deploy/test/servers/cpsim/cpsim_driver.py:206`, `:210`), so the final stored sample is never written to the data file.
- `CPSim.change_plate` swaps only `self.data` and never assigns `self.loaded_plate`, which is set once at startup (`helao/deploy/test/servers/cpsim/cpsim_driver.py:55`, `:75-90`). `get_loaded_plate` and `change_plate` therefore always report the startup `plate_id`, even after a successful switch. An unknown plate id makes `change_plate` return `False` to the caller; it is logged only at INFO (`cpsim_driver.py:89`) and the action still finishes without error.
