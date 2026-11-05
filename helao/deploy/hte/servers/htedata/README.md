# htedata

Action server for plate information lookups (platemap, screening-print elements, info-file and print/anneal-record checks) for a `plate_id`. It wraps the legacy `HTEdata` driver, which calls the plate API (`helao/helpers/plate_api.py`).

## Vendor software

No vendor software beyond the env files. The plate API client needs the `HELAO_CREDENTIALS` environment variable (path to its credentials/environment file; see `helao/helpers/plate_api.py`), which is not a vendor package.

## Params

Host-level keys every server accepts: see docs/config-schema.md ("Group conventions for `params:`").

### `HTEdata_server` (`fast:`)

No module-specific keys. `HTEdata.__init__` stores the params dict as `config_dict` but never reads a key from it (`helao/deploy/hte/servers/htedata/HTEdata_legacy.py:133`). No shipped station config uses this server.

Example:
```yaml
params: {}
```
