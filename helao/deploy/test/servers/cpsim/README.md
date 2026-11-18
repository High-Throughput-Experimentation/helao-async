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
| `elements` | list[str] | list, first row only | none | element symbols of the selected composition (`el_str` split on `-`) | `helao/deploy/test/servers/cpsim/cpsim_driver.py:185` |
| `atfracs` | list[unknown (dynamic)] | list, first row only | at. % (as stored) | fraction of each element; type comes from the stored dataset, not from code | `helao/deploy/test/servers/cpsim/cpsim_driver.py:185` |
| `t_s` | list[float] | list slice per row (empty in the first row) | s | time since trace start | `helao/deploy/test/servers/cpsim/cpsim_driver.py:206` |
| `erhe_v` | list[float] | list slice per row (empty in the first row) | V vs RHE | working-electrode potential | `helao/deploy/test/servers/cpsim/cpsim_driver.py:206` |
| `<column>` | unknown (dynamic) | list slice per row | unknown (dynamic) | every other key of the stored `CP3` dict; the set is fixed by the dataset `oer13_cps.pzstd`, not by code | `helao/deploy/test/servers/cpsim/cpsim_driver.py:188`, `:206` |

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
| `loaded_plate_id` | int | scalar per row | none | plate currently loaded in the driver | `helao/deploy/test/servers/cpsim/cpsim_server.py:95` |
| `orch_key` | str | scalar per row | none | requesting orchestrator server key | `helao/deploy/test/servers/cpsim/cpsim_server.py:96` |
| `orch_host` | str | scalar per row | none | requesting orchestrator host | `helao/deploy/test/servers/cpsim/cpsim_server.py:97` |
| `orch_port` | int | scalar per row | none | requesting orchestrator port | `helao/deploy/test/servers/cpsim/cpsim_server.py:98` |

Action results (in `-act.json`):

| key | in | type | structure | meaning | set at |
|---|---|---|---|---|---|
| `_loaded_plate_id` | `action_params` | int | scalar | copy of `loaded_plate_id` | `helao/deploy/test/servers/cpsim/cpsim_server.py:100` |
| `_orch_key` | `action_params` | str | scalar | copy of `orch_key` | `helao/deploy/test/servers/cpsim/cpsim_server.py:100` |
| `_orch_host` | `action_params` | str | scalar | copy of `orch_host` | `helao/deploy/test/servers/cpsim/cpsim_server.py:100` |
| `_orch_port` | `action_params` | int | scalar | copy of `orch_port` | `helao/deploy/test/servers/cpsim/cpsim_server.py:100` |

### `change_plate` (action)

Writes one row and one `action_params` key; writer `helao/deploy/test/servers/cpsim/cpsim_server.py:114-115`.

Data file `<action_abbr>-*.jsonl` (+ `.meta.json`), one row:

| field | type | structure | unit | meaning | written at |
|---|---|---|---|---|---|
| `loaded_plate_id` | int | scalar per row | none | plate loaded after the switch | `helao/deploy/test/servers/cpsim/cpsim_server.py:115` |

Action results (in `-act.json`):

| key | in | type | structure | meaning | set at |
|---|---|---|---|---|---|
| `_loaded_plate_id` | `action_params` | int | scalar | plate loaded after the switch | `helao/deploy/test/servers/cpsim/cpsim_server.py:114` |

## Notes

- `_poll` emits `v[last_idx:newest_idx]`, a half-open slice, and finishes when `newest_idx` reaches the last index (`helao/deploy/test/servers/cpsim/cpsim_driver.py:206`, `:210`), so the final stored sample is never written to the data file.
