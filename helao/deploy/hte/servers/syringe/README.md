# syringe

KD Scientific Legato 100 syringe pump action server (`syringe_server`, driver `KDS100` in `legato_driver.py`): infuse and withdraw over an RS-232 chain, with a status poller.

## Vendor software
No vendor software beyond the env files (`pyserial` is in `environment.yml` and the root env). The pump takes RS-232 at a fixed 115200 baud; no vendor driver is loaded.

## Params
Host-level keys every server accepts: see `docs/config-schema.md` ("Group conventions for `params:`").

### `syringe_server` (`fast:` value)
| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `port` | yes | string | none | Serial port of the pump chain (for example `COM3`). `KeyError` inside `connect()`, which is caught: the connect then fails and is logged. | `helao/deploy/hte/servers/syringe/legato_driver.py:143` |
| `pumps` | yes | dict | none | `{pump_name: {address: int, diameter: float}}`. `address` is the pump's chain address; `diameter` is the syringe inner diameter in mm, sent to the pump at startup. The poller, safe-state and setup loops use every entry. A pump action uses only the first entry in the dict (one pump per COM port). Missing `pumps`: `KeyError` in the action; the loops treat it as no pumps. | `helao/deploy/hte/servers/syringe/legato_driver.py:205`, `:486`, `:509`, `:544`, `:616` |
| `pump_addrs` | no | dict | `{}` | Only its keys are read, as pump names for the time-query helpers. No existing config sets it, so those helpers do nothing when called without a pump name. | `helao/deploy/hte/servers/syringe/legato_driver.py:389`, `:418`, `:441`, `:458` |

Example:
```yaml
params:
  port: COM3
  pumps:
    zero:
      address: 0
      diameter: 26.7
```
Notes:
- The docstring of `KDS100` lists only `port` and `pumps`; `pump_addrs` is read in code but documented nowhere else.
