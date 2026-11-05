# kinesis

Action server for Thorlabs Kinesis motors (one `KinesisMotor` per configured axis, via pylablib).

## Vendor software

Install by hand (not pip/conda):

- Thorlabs Kinesis software: installs the FTDI D2XX driver that `pyft232` (see requirements.txt) talks through. pylablib does not load Kinesis DLLs. The code does not say where to download it; Thorlabs distributes it.

## Params

Host-level keys every server accepts: see docs/config-schema.md ("Group conventions for `params:`").

### `kinesis_server` (`fast:`)

| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `axes` | yes | dict | none | `{axis_name: {...}}`; indexed without a default, so a missing key raises `KeyError` at startup. Axis names become the `axis` enum of `kmove`. An empty dict registers no motion endpoints. | `helao/deploy/hte/servers/kinesis/kinesis_server.py:175`, `kinesis_driver.py:77` |
| `axes.<axis>.serial_no` | yes | str | none | Device serial number, passed as `conn` to `Thorlabs.KinesisMotor`. | `kinesis_driver.py:90` |
| `axes.<axis>.pos_scale` | yes | float | none | Counts per mm. Also used by the UI and by `query_axis_positions` (missing or 0 gives mm `None`). | `kinesis_driver.py:85`, `kinesis_driver.py:163` |
| `axes.<axis>.vel_scale` | yes | float | none | Device units to mm/s, passed to pylablib `scale`. | `kinesis_driver.py:86` |
| `axes.<axis>.acc_scale` | yes | float | none | Device units to mm/s^2, passed to pylablib `scale`. | `kinesis_driver.py:87` |
| `axes.<axis>.move_limit_mm` | no | float | `3.0` | A move runs only when its target position is below this value; a target >= `move_limit_mm` is refused (logged, not moved). | `kinesis_server.py:119` |
| `warn_above_mm` | no | dict | `{}` | `{axis: mm}`. Read only by the `motion_control_inverse_scale` panel (`control_vis`): displacement above which a move asks for a second click. Falls back to `axes.<axis>.move_limit_mm`, then 10.0 mm. | `helao/ui/shared/motion_control.py:356` (fallback 10.0 at `:98`) |

Example:
```yaml
params:
  axes:
    z:
      serial_no: "49535954"
      pos_scale: 1228800.0  # device to mm
      vel_scale: 65970697.6  # device to mm/s
      acc_scale: 13518.2  # device to mm/s2
      move_limit_mm: 3.0
```

Notes:
- A failed `connect()` for one axis aborts the loop, so later axes are not opened (`kinesis_driver.py:83`).
- The limit check compares only against the upper bound; negative targets are not checked (`kinesis_server.py:119`).
