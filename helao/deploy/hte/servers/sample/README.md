# sample

Sample archive action server (`sample_server`): tracks samples in trays and named custom positions, persists them to `<host>_archive.json` under `STATES/`, and syncs sample records with the sample database. `bokeh/sample_vis.py` and `reflex/sample_vis.py` show the newest samples.

## Vendor software
No vendor software beyond the env files.

## Params
Host-level keys every server accepts: see `docs/config-schema.md` ("Group conventions for `params:`").

### `sample_server` (`fast:` value)
| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `positions` | no | dict | none (no trays, no custom positions) | Sample-archive layout. Keys: `tray<n>` (integer `n`) and `custom`. Any other key is ignored. At most one server per config may declare it. | `helao/deploy/hte/servers/sample/archive_driver.py:123`, `helao/deploy/hte/servers/sample/sample_server.py:76` |
| `positions.tray<n>` | no | dict or null | n/a | Slots of tray `n`. Keys `slot1`, `slot2`, `slot3`; any other slot key is logged and skipped. A null tray is skipped. | `helao/deploy/hte/servers/sample/archive_driver.py:285` |
| `positions.tray<n>.slot<m>` | no | string or null | n/a | Vial rack type in the slot: `VT54`, `VT15` or `VT70`. Null leaves the slot empty. Any other string is logged as unsupported and the slot is stored as empty. | `helao/deploy/hte/servers/sample/archive_driver.py:296` |
| `positions.custom` | no | dict | `{}` | `{custom_name: custom_type}`. `custom_type` must be one of `cell`, `reservoir`, `injector`, `waste` (`CustomTypes`); another value fails pydantic validation. The names also become the `dev_custom` enum of the endpoints that take a `custom` argument. | `helao/deploy/hte/servers/sample/archive_driver.py:260`, `helao/deploy/hte/servers/sample/sample_server.py:77`, `helao/helpers/sample_positions.py:39` |

The persisted `<host>_archive.json` is compared with `positions` at startup. If tray or custom layouts differ, the archive's positions are replaced by the config's.

Example:
```yaml
params:
  positions:
    tray1:
      slot1: null
      slot2: null
      slot3: null
    tray2:
      slot1: VT54
      slot2: VT54
      slot3: VT54
    custom:
      elec_res1: reservoir
      cell1_we: cell
```

### `sample_vis` (`bokeh:` / `reflex:` panel)
Reads no params of its own. The Reflex panel looks up the server's `host` and `port` in the config (`helao/deploy/hte/servers/sample/reflex/sample_vis.py:109`).
