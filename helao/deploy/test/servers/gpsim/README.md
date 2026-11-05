# gpsim

Simulated Gaussian-process acquisition server (`gpsim_server`, driver `GPSim`, model code in `gp_backend.py`): proposes and "measures" points from the stored OER dataset. `bokeh/gpsim_live_vis.py` and `reflex/gpsim_panel.py` show the state.

## Vendor software
No vendor software beyond the env files. `gpytorch` and `pytorch-cpu` come from this folder's `environment.yml`.

## Params
Host-level keys every server accepts: see `docs/config-schema.md` ("Group conventions for `params:`").

### `gpsim_server` (`fast:` value)
| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `random_seed` | yes | int | none | Seed of the driver's NumPy random generator. `KeyError` at startup if absent. The `initialize_global` action has its own `random_seed` action param (default `9999`); that is a separate value. | `helao/deploy/test/servers/gpsim/gpsim_driver.py:80` |
| `minimize` | no | bool | `True` | `True`: targets are `-eta`, so the search minimizes overpotential. `False`: targets are `+eta`. No existing config sets it. | `helao/deploy/test/servers/gpsim/gpsim_driver.py:98` |

Example (from `demo0.yml`):
```yaml
params:
  random_seed: 9999
```

The panels (Bokeh and Reflex) read no params.
