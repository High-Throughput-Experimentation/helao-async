# tec

Meerstetter TEC temperature controller action server (`tec_server`, driver `MeerstetterTEC` in `mecom_driver.py`): reads TEC telemetry, enables or disables the control loop and sets the target temperature. `bokeh/tec_vis.py` plots it.

## Vendor software
- `pyMeCom` (Python module `mecom`): listed in this folder's `requirements.txt` and the root `requirements.txt`, installed from `https://github.com/meerstetter/pyMeCom/archive/master.zip`. It is not on conda; pip/uv installs it.
- No Meerstetter PC software or serial driver is required by the code; the TEC is reached over a serial port.

## Params
Host-level keys every server accepts: see `docs/config-schema.md` ("Group conventions for `params:`").

### `tec_server` (`fast:` value)
| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `port` | yes | string | none | Serial port of the TEC (passed to `MeCom(serialport=...)`). `KeyError` at startup if absent. | `helao/deploy/hte/servers/tec/mecom_driver.py:84`, `:101` |
| `channel` | yes | int | none | TEC channel (parameter instance). `KeyError` at startup if absent. | `helao/deploy/hte/servers/tec/mecom_driver.py:83` |
| `queries` | no | list of string | `DEFAULT_QUERIES` = `enabled_status`, `object_temperature`, `target_object_temperature`, `output_current`, `temperature_is_stable` | Parameters polled into `tec_vals`. Allowed names (`COMMAND_TABLE`): `device_status`, `enabled_status`, `temperature_is_stable`, `object_temperature`, `target_object_temperature`, `output_current`, `output_voltage`, `sink_temperature`, `ramp_temperature`. | `helao/deploy/hte/servers/tec/mecom_driver.py:85`, `:32`, `:42` |
| `retries` | no | int | `15` | Connection attempts when the handshake raises `ResponseTimeout`. Another error ends the attempts at once. | `helao/deploy/hte/servers/tec/mecom_driver.py:112` |
| `start_margin` | no | number | `0` | Stored on the driver but not used (the docstring says "carried for parity"). | `helao/deploy/hte/servers/tec/mecom_driver.py:91` |
| `allow_no_sample` | no | bool | `True` | Stored on the driver but not used. | `helao/deploy/hte/servers/tec/mecom_driver.py:96` |

Notes:
- The poll interval comes from the server-level key `polling_time` (default 0.1 s, read by `ActionHost`), not from `params`.
- No `hte` or `test` config uses this server, so the example is built from the code defaults.

Example:
```yaml
params:
  port: COM5
  channel: 1
  queries: [object_temperature, target_object_temperature, output_current]
  retries: 15
```

### `tec_vis` (`bokeh:` panel)
Reads no params of its own.
