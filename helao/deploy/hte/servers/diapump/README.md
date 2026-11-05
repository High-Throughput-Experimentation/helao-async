# diapump

Action server for a KNF SIMDOS RC-P diaphragm dosing pump on RS-485 (continuous-rate runs, polling, direct start/stop).

## Vendor software

No vendor software beyond the env files (`pyserial`, from `environment.yml`).

## Params

Host-level keys every server accepts: see docs/config-schema.md ("Group conventions for `params:`").

### `diapump_server` (`fast:`)

| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `port` | yes | str | none (KeyError in `connect` if absent) | Serial port of the RS-485 adapter (for example `COM7`). Opened at 9600 baud. | `helao/deploy/hte/servers/diapump/simdos_driver.py:171` |
| `address` | yes | int | none (KeyError on first command) | Pump RS-485 device address. Formatted with `:02`, so it must be an int, not a string. | `helao/deploy/hte/servers/diapump/simdos_driver.py:216` |

Example:
```yaml
params:
  port: COM7
  address: 0
```
