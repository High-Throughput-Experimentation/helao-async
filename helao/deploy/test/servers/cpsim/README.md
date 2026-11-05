# cpsim

Simulated potentiostat (`cpsim_server`, driver `CPSim`): replays stored OER chronopotentiometry traces from `helao/deploy/test/demos/data/oer13_cps.pzstd`. `bokeh/oersim_vis.py` and `reflex/oersim_panel.py` plot them.

## Vendor software
No vendor software beyond the env files.

## Params
Host-level keys every server accepts: see `docs/config-schema.md` ("Group conventions for `params:`").

### `cpsim_server` (`fast:` value)
| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `plate_id` | yes | int | none | Plate loaded at startup. Must be a key of the dataset, else `KeyError` at startup. `change_plate` switches it later. | `helao/deploy/test/servers/cpsim/cpsim_driver.py:55` |
| `column_aliases` | no | dict `{stored_name: emitted_name}` | `{}` | Renames emitted columns so the simulator can feed a panel written for other hardware. A value that is not a dict is treated as empty. | `helao/deploy/test/servers/cpsim/cpsim_driver.py:60` |

Example (from `htereflex.yml`):
```yaml
params:
  plate_id: 2750
  column_aliases:
    erhe_v: Ewe_V
```

The panels `oersim_vis` (Bokeh and Reflex) read no params.
