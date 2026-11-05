# galil_io

Action server for the digital and analog IO of a Galil controller: digital in/out, analog in/out, DMC-program digital cycles, and an analog-input monitor.

## Vendor software

Install by hand (not pip/conda), on Windows or Linux:

1. The Galil gclib C library: the vendor installer on Windows, the Galil package
   repository on Linux (https://www.galil.com/sw/pub/all/doc/gclib/html/).
2. One gclib Python wrapper. Both install as `import gclib`, so an env holds one,
   and the server's `gclib_api` param must match it:
   - `gclib_api: "1"` (default): wrapper 1.0.1, the `gclib.py()` API, from the
     gclib installation's Python wrapper (gclib 2.4.1 Python docs). From the
     helao env on Windows:
     `python "C:\Program Files (x86)\Galil\gclib\source\wrappers\python\setup.py" install`.
     On Linux, run the same `setup.py install` from the `wrappers/python` folder
     of the gclib installation. Alternative (`setup.py install` is deprecated
     in current setuptools): `python -m pip install "<gclib install>/source/wrappers/python"`.
   - `gclib_api: "2"`: wrapper 2.x, the `gclib.Controller` API (Python >= 3.12):
     `pip install --upgrade --index-url https://www.galil.com/sw/pub/python gclib`
     (docs: https://www.galil.com/sw/pub/python/doc/index.html).
     Not yet verified at a station (reply trimming, gcaps bypass, unsolicited
     output without `-s ALL`): before using `"2"` in production, run
     `helao/deploy/hte/tests/smoke/golden_capture_galil.py` and
     `golden_capture_galil_io.py` with `"1"` and with `"2"` and diff the captures.

A mismatch fails at connect with a message naming `gclib_api`.

## Params

Host-level keys every server accepts: see docs/config-schema.md ("Group conventions for `params:`").

### `galil_io` (`fast:`)

All keys are read by the `Galil` driver (`helao/deploy/hte/servers/galil_io/galil_io_driver.py`); `galil_io.py` itself reads none.

| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `galil_ip_str` | no (the server starts but is not connected without it) | str | `None` | Controller IP. `connect` opens `"<ip> --direct -s ALL"`. When empty or absent, `connect` logs "no Galil IP configured" and returns a failed response. | `helao/deploy/hte/servers/galil_io/galil_io_driver.py:133` |
| `dev_ai` | no | dict[str, int] | `{}` | Analog-input channels, `{name: port}`. Names become the `dev_ai` action enum. Read with `MG @AN[port]`. | `helao/deploy/hte/servers/galil_io/galil_io_driver.py:95` |
| `dev_ao` | no | dict[str, int] | `{}` | Analog-output channels, `{name: port}`. Names become the `dev_ao` enum. | `helao/deploy/hte/servers/galil_io/galil_io_driver.py:104` |
| `dev_di` | no | dict[str, int] | `{}` | Digital-input channels, `{name: port}`. Read with `MG @IN[port]`; also the trigger names for digital cycles. | `helao/deploy/hte/servers/galil_io/galil_io_driver.py:107` |
| `dev_do` | no | dict[str, int] | `{}` | Digital-output channels, `{name: port}`. Read and set with `@OUT[port]`; also the output names for digital cycles. | `helao/deploy/hte/servers/galil_io/galil_io_driver.py:110` |
| `monitor_ai` | no | dict[str, number] | `{}` | `{ai_name: scale}` polled by `GalilPoller`; each raw reading is multiplied by `scale`. Names not present in `dev_ai` are dropped. | `helao/deploy/hte/servers/galil_io/galil_io_driver.py:100` |
| `gclib_api` | no | str `"1"` or `"2"` (YAML int `1`/`2` accepted) | `"1"` | Which gclib Python wrapper API the env holds (see Vendor software). Any other value raises `ValueError` when the driver is constructed. | `helao/deploy/hte/servers/galil_motion/galil_channels.py:25` (called from `galil_io_driver.py:119`) |

Example:
```yaml
params:
  galil_ip_str: 192.168.x.x
  gclib_api: "1"
  dev_ai:
    cell_pressure_psi: 1
  dev_di:
    gamry_ttl0: 1
  dev_do:
    spec_trig: 5
    we_pump: 7
  monitor_ai:
    cell_pressure_psi: 5.0
```

## Notes

- `visualizer/pressure_vis.py` also reads the `dev_ai` keys from this server's `params` to build its pressure display.
- The `.dmc` files in this folder are the DMC programs the digital-cycle actions upload.
