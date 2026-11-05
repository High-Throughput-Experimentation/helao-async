# co2sensor

Action server for a SprintIR-6S NDIR CO2 sensor on a serial port. It polls CO2 ppm and records it on request (`acquire_co2`, `cancel_acquire_co2`). `bokeh/co2_vis.py` and `reflex/co2_vis.py` are its live visualizers (`live_vis: co2_vis`).

## Vendor software

No vendor software beyond the env files (`pyserial`, from `environment.yml`).

## Params

Host-level keys every server accepts: see docs/config-schema.md ("Group conventions for `params:`").

### `co2sensor_server` (`fast:`)

| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `port` | yes | str | none (KeyError in `connect` if absent) | Serial port or device path of the sensor (for example `COM12` or `/dev/ttyUSB0`). Opened at 9600 baud. | `helao/deploy/hte/servers/co2sensor/sprintir_driver.py:82` |
| `start_margin` | no | number | `0` | Stored by the driver; nothing in this folder reads it (unused). | `helao/deploy/hte/servers/co2sensor/sprintir_driver.py:68` |

The Bokeh and Reflex visualizer modules read no server params.

Example:
```yaml
params:
  port: COM12
  start_margin: 0
```
