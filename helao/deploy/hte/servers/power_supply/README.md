# power_supply

Action server for a VISA serial bench power supply (Korad/RND-style `VSET1:`/`ISET1:`/`OUT1` command set): constant voltage, square wave, and constant-current square wave.

## Vendor software

No vendor software beyond the env files. `pyvisa` and `pyvisa-py` are in `environment.yml`. The driver calls `pyvisa.ResourceManager()` with no backend argument, so an installed VISA runtime is used if pyvisa finds one; otherwise pyvisa-py is used.

## Params

Host-level keys every server accepts: see docs/config-schema.md ("Group conventions for `params:`").

### `power_supply_server` (`fast:`)

The `power_supply_vis` panels (`action_vis:`) read no params.

| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `resource_name` | yes | str | `None` | VISA resource string, e.g. `ASRL/dev/ttyUSB0::INSTR` or `ASRL3::INSTR`. Not checked at start; `connect()` fails if it is missing or wrong. | `helao/deploy/hte/servers/power_supply/power_supply_driver.py:48` |
| `timeout_ms` | no | int | `10000` | VISA I/O timeout in milliseconds. | `power_supply_driver.py:49` |

Example:
```yaml
params:
  resource_name: 'ASRL/dev/ttyUSB0::INSTR'
  timeout_ms: 10000
```

Notes:
- The server sets `app.server_params["allow_concurrent_actions"] = False` in code, overriding any config value (`power_supply_server.py:476`).
