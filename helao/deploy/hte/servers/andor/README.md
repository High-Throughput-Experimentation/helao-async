# andor

Action server for an Andor Zyla camera with an optional spectrograph (`andor_server.py`): acquisition, sensor cooling, ND-filter adjustment and lamp wavelength calibration. `wl_source` selects one of two driver variants (`spectrograph.py`, `calibrated.py`) on a shared base (`driver.py`). `reflex/andor_vis.py` is its Reflex panel. Design notes: `CLAUDE.md` in this folder.

## Vendor software

Install by hand (not pip/conda):

- Andor SDK3, with the `pyAndorSDK3` wheel from the SDK. Both variants need it; the driver imports it lazily in `connect()` (`driver.py:41`).
- The `pyAndorSpectrograph` wheel from the SDK. Only `wl_source: spectrograph` (the default) needs it; `spectrograph.py` is the only module that imports it (`spectrograph.py:31`). A station with `wl_source: calibration` does not need it.

The code does not say where the SDK is downloaded from. Take both wheels from the Andor SDK installation.

## Params

Host-level keys every server accepts: see docs/config-schema.md ("Group conventions for `params:`").

### `andor_server` (`fast:`)

| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `wl_source` | no | str | `"spectrograph"` | Driver variant. `"spectrograph"`: wavelength axis from the ATSpectrograph `GetCalibration`. `"calibration"`: axis from a lamp-calibration fit persisted under `<STATES>`; no spectrograph needed. Any other value raises `ValueError` when the app is built. | `helao/deploy/hte/servers/andor/andor_server.py:548` |
| `dev_id` | no | int | `0` | Index of the camera to open through the SDK. | `helao/deploy/hte/servers/andor/driver.py:130` |
| `states_root` | no | str (path) | `"STATES"` (cwd-relative, logs a WARNING) | Directory holding the persisted wavelength calibration file. Used only when the host provides no `states_root` of its own; the host value wins. | `helao/deploy/hte/servers/andor/driver.py:166` |
| `host` | no | str | `socket.gethostname()` | Host name used in the calibration file name `<host>_<server_key>_andor_wl_calib.json`. | `helao/deploy/hte/servers/andor/driver.py:174` |

The Reflex module `reflex/andor_vis.py` reads no server params.

Example:
```yaml
params:
  dev_id: 0
  wl_source: spectrograph
```

## Notes

- `andor_dyn_endpoints` writes `server_params["allow_concurrent_actions"] = False` at startup (`andor_server.py:323`); a config value for it is overwritten.
- `driver.py:158-165` says a driver built as `driver_class(config=self.server_params)` has no `_base_hook`, so `states_root` may fall through to the cwd-relative default. Whether that happens in a launched server was not checked here; set `states_root` explicitly if the WARNING appears.
