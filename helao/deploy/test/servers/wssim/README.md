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
