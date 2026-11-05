# calc

Action server for in-sequence calculations (UV-Vis absorbance, CO2 purge check, syringe fill check, OCV and CP bounds) that do not produce `Analysis` models.

## Vendor software

No vendor software beyond the env files.

## Params

Host-level keys every server accepts: see docs/config-schema.md ("Group conventions for `params:`").

### `calc_server` (`fast:`)

No server-level keys. `Calc.__init__` stores the params dict as `config_dict` (`helao/deploy/hte/servers/calc/calc_driver.py:112`) but nothing reads a key from it. Calculation inputs arrive as per-action parameters instead.

Example:
```yaml
params: {}
```
