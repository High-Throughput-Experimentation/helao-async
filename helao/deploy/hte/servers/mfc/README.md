# mfc

Action server for Alicat mass flow controllers on serial ports (flow, pressure, gas, valve hold, tare, and CO2 concentration holding).

## Vendor software

No vendor software beyond the env files. The Alicat serial protocol is implemented in-tree (`alicat_driver.py`, `FlowController`) on top of `pyserial`, which is in `environment.yml`.

## Params

Host-level keys every server accepts: see docs/config-schema.md ("Group conventions for `params:`").

### `mfc_server` (`fast:`)

The bokeh/reflex `mfc_vis` panels (`live_vis:`) read only `devices`.

| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `devices` | yes | dict | none | `{device_name: {port, unit_id}}`. Indexed without a default in the server, so a missing key raises `KeyError`. Device names become the `device_name` enum of the endpoints. An empty dict registers no endpoints. | `helao/deploy/hte/servers/mfc/mfc_server.py:74`, `alicat_driver.py:78`, `bokeh/mfc_vis.py:86` |
| `devices.<name>.port` | yes | str | none | Serial port of the controller (e.g. `COM6`, `/dev/ttyUSB0`). | `alicat_driver.py:159` |
| `devices.<name>.unit_id` | yes | str | none | Alicat unit address letter, also the response prefix stripped from gas and manufacturer queries. | `alicat_driver.py:159`, `alicat_driver.py:192` |
| `co2_server_name` | no | str | `None` | Server key of the CO2 sensor server in the same config. `maintain_concentration` and `cancel_maintain_concentration` are registered only when this key names a server present in the config (and `devices` is non-empty). The executor reads that server's `host` and `port` and subscribes to its `ws_live`. | `mfc_server.py:73`, `mfc_server.py:77`, `alicat_driver.py:784` |

Example:
```yaml
params:
  devices:
    CO2:
      port: COM6
      unit_id: A
  co2_server_name: CO2SENSOR
```

Notes:
- If `co2_server_name` is unset or not in the config, the executor does not open a CO2 websocket (`alicat_driver.py:789`).
