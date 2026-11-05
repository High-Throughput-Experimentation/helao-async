# o2sensor

Action server for the CM-0134 dissolved-oxygen sensor on Modbus-RTU over a serial port: continuous O2 ppm acquisition.

## Vendor software

No vendor software beyond the env files. `pyserial` and `minimalmodbus` are in `environment.yml`.

## Params

Host-level keys every server accepts: see docs/config-schema.md ("Group conventions for `params:`").

### `o2sensor_server` (`fast:`)

All keys are optional; the defaults are used when a key is absent.

| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `device` | no | str | `"COM7"` | Serial port, e.g. `COM7` or `/dev/ttyUSB0`. | `helao/deploy/hte/servers/o2sensor/cm0134_driver.py:75` |
| `address` | no | int | `254` | Modbus device address. | `cm0134_driver.py:76` |
| `baudrate` | no | int | `9600` | Serial baud rate. | `cm0134_driver.py:78` |
| `start_margin` | no | number | `0` | Stored on the driver; nothing else in the module reads it. | `cm0134_driver.py:58` |
| `allow_no_sample` | no | bool | `True` | Stored on the driver; nothing else in the module reads it. | `cm0134_driver.py:63` |

Example (no shipped station config uses this server; values are the defaults):
```yaml
params:
  device: COM7
  address: 254
  baudrate: 9600
```

Notes:
- `start_margin` and `allow_no_sample` are documented in the driver docstring but have no effect on the code paths in this folder.
