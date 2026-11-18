# wssim

Websocket data simulator (`ws_simulator`, driver `WsSim`): pushes random synthetic series into the live buffer at 10 Hz so live panels can be exercised without hardware. `bokeh/wssim_live_vis.py` and `reflex/wssim_panel.py` plot them.

## Vendor software
No vendor software beyond the env files.

## Params
Host-level keys every server accepts: see `docs/config-schema.md` ("Group conventions for `params:`").

### `ws_simulator` (`fast:` value)
| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `columns` | no | dict `{column_name: scale}` | six series `series_0` ... `series_5` with scales 1, 2, 5, 10, 50, 100 | Emitted columns. Each sample is `scale * uniform[0, 1)`. Names are chosen so a live panel written for real hardware (which keys its rolling means off column names) can be driven. An empty or non-dict value falls back to the default six; each scale is converted with `float`. | `helao/deploy/test/servers/wssim/ws_simulator.py:65` |

Example (from `htereflex.yml`):
```yaml
params:
  columns:
    pressure_psi_0: 15
    pressure_psi_1: 30
```

The panels (Bokeh and Reflex) read no params.

## Outputs

### `acquire_data` (action)

Streams the simulator's live buffer into one data file, one row per poll; executor `WsExec` (`helao/deploy/test/servers/wssim/ws_simulator.py:168`), `action_abbr` `WsSim` (`:167`). File `WsSim-<orch_submit_order>.<action_order>.<action_retry>.<action_split>__<n>.jsonl` plus `.meta.json` (`helao/hexagon/adapters/native/data_file.py:172`). Columns are the keys of the first row.

Data file `WsSim-*.jsonl` (+ `.meta.json`):

| field | type | structure | unit | meaning | written at |
|---|---|---|---|---|---|
| `epoch_s` | float | scalar per row | s (Unix epoch) | wall-clock stamp of the buffered sample | `helao/deploy/test/servers/wssim/ws_simulator.py:120` (stamp `helao/hexagon/app/action_host.py:403`) |
| `<column>` | float | scalar per row | none | `scale * uniform[0, 1)` for each configured column (default `series_0` ... `series_5`); names come from the `columns` param | `helao/deploy/test/servers/wssim/ws_simulator.py:121` (value `:85`) |

Action results: none (`acquire_data` does not write `action_params` at run time).

### `cancel_acquire_data` (action)

No data files or action results.

### Live data (status/ws stream)

Published by `WsSim.poll_data_loop` at 10 Hz, independent of any action (`helao/deploy/test/servers/wssim/ws_simulator.py:86`).

| field | type | structure | unit | meaning | written at |
|---|---|---|---|---|---|
| `sim_dict` | dict | dict | none | `{<column>: float}` as above; each value is stamped `(value, epoch)` | `helao/deploy/test/servers/wssim/ws_simulator.py:85-86` |
