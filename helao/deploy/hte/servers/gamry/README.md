# gamry

Action server for Gamry potentiostats (`gamry_server2.py`, over the GamryCOM Windows COM interface). It exposes LSV, CA, CP, CV, OCV, RCA, PEIS and GEIS techniques. `bokeh/gamry_vis.py` and `reflex/gamry_vis.py` are its action visualizers (`action_vis: gamry_vis`).

## Vendor software

Install by hand (not pip/conda):

- Gamry Framework (provides the GamryCOM COM server used through `comtypes`). The driver loads the GamryCOM type library by GUID `{BD962F0D-A990-4823-9CF5-284D1CDD9C6D}`.

`comtypes` itself is installed on Windows by `requirements.txt` in this folder. The driver imports it inside `connect()`, so the module imports on Linux, but the server only works on Windows.

## Params

Host-level keys every server accepts: see docs/config-schema.md ("Group conventions for `params:`").

### `gamry_server2` (`fast:`)

The `GamryDriver` receives the server's `params` dict as its config (through `GamryComAdapter`, `gamry_com.py:299`). The server module reads none itself. The Bokeh and Reflex visualizer modules read no server params.

| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `dev_id` | yes | int | `None` | Index into `GamryDeviceList.EnumSections()` selecting the potentiostat. When absent, indexing the list with `None` raises and `connect` fails. | `helao/deploy/hte/servers/gamry/driver.py:87`, `:104` |
| `filterfreq_hz` | no | number (Hz) | `1000.0` | Analog input filter for the I and V channels. | `helao/deploy/hte/servers/gamry/driver.py:88`, `:269`, `:281` |
| `grounded` | no | bool | `True` | Passed to `SetGround`. | `helao/deploy/hte/servers/gamry/driver.py:89`, `:259` |
| `recover_stale_gamrycom` | no | bool | `False` | When `pstat.Open()` fails with "in use by another script", kill every GamryCOM process on the host and retry the open once. Leave it off where another live instance may hold the device. | `helao/deploy/hte/servers/gamry/driver.py:149` |

Example:
```yaml
params:
  dev_id: 0
  filterfreq_hz: 1000.0
  grounded: true
```

### Unused keys seen in configs

- `allow_no_sample` (set to `true` in several `hte` configs): no code in this folder reads it.
- `address`, `num_channels` (commented out in `hte` configs): no code in this folder reads them.

## Notes

- `gamry_dyn_endpoints` writes `server_params["allow_concurrent_actions"] = False` at startup (`gamry_server2.py:656`). The server sets this itself; a config value is overwritten.
- `driver.py:89` stores `grounded` as `int(...)`, while `driver.py:259` re-reads the raw value for `SetGround`. Both come from the same key.
