# spec

Spectral Products SM303 USB spectrometer action server (`spec_server`, driver `SM303` in `spectral_products_driver.py`): externally triggered or timed spectrum acquisition, with panels `bokeh/spec_vis.py` and `reflex/spec_vis.py`.

## Vendor software
Install by hand (not pip/conda):

- Spectral Products SM32 USB software and SDK (Windows). The driver loads the SDK DLL with `ctypes.CDLL` from the `lib_path` param. Existing configs point at `C:\Spectral Products\SM32ProForUSB\SDK Examples\DLL\x64\stdcall\SPdbUSBm.dll`; the driver's own messages call the file `SMdbUSBm.dll`. Use the 64-bit `stdcall` DLL that matches the Python build.
- The driver fails to connect (status uninitialized, `spec` is `None`) if the file at `lib_path` does not exist.
- The code and docs do not say where Spectral Products distributes the installer.

## Params
Host-level keys every server accepts: see `docs/config-schema.md` ("Group conventions for `params:`").

### `spec_server` (`fast:` value)
| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `lib_path` | yes | string | none | Path of the SDK DLL. `KeyError` at startup if absent. | `helao/deploy/hte/servers/spec/spectral_products_driver.py:100`, `:142` |
| `dev_num` | yes | int | none | SDK device channel number (passed to every `sp*GivenChannel` call as `c_short`). `KeyError` at startup if absent. | `helao/deploy/hte/servers/spec/spectral_products_driver.py:103` |
| `n_pixels` | yes | int | none | Detector pixel count (1024 for the SM303). `KeyError` at startup if absent. After construction it is used only in log messages. | `helao/deploy/hte/servers/spec/spectral_products_driver.py:101`, `:263` |
| `start_margin` | yes | number (s) | none | Seconds added to the trigger duration when waiting for the trigger and when deciding the polling loop is complete. `KeyError` at startup if absent. | `helao/deploy/hte/servers/spec/spectral_products_driver.py:102`, `helao/deploy/hte/servers/spec/spec_server.py:94`, `:111` |
| `allow_no_sample` | no | bool | `False` | `True`: acquisition endpoints run without `samples_in`. `False`: a request with no sample in is rejected. | `helao/deploy/hte/servers/spec/spectral_products_driver.py:128`, `helao/deploy/hte/servers/spec/spec_server.py:459` |

Notes:
- The server sets `allow_concurrent_actions` to `False` in code (`helao/deploy/hte/servers/spec/spec_server.py:180`); the config value is overridden.
- The driver has commented-out reads of `wl_cal` and `px_cal`; they are not read.

Example:
```yaml
params:
  dev_num: 0
  lib_path: 'C:\Spectral Products\SM32ProForUSB\SDK Examples\DLL\x64\stdcall\SPdbUSBm.dll'
  n_pixels: 1024
  start_margin: 5
  allow_no_sample: true
```

### `spec_vis` (`action_vis:` / `live_vis:` panel, Bokeh and Reflex)
Reads no params of its own. The Reflex panel looks up the server's `host` and `port` in the config (`helao/deploy/hte/servers/spec/reflex/spec_vis.py:73`).
