# analysis

Action server that exposes one `analyze_<module>` endpoint per configured analysis class and runs queued analyses on a worker pool (`AnalysisSyncer`), optionally uploading results to S3.

## Vendor software

No vendor software beyond the env files.

## Params

Host-level keys every server accepts: see docs/config-schema.md ("Group conventions for `params:`").

### `analysis_server` (`fast:`)

`makeApp` delegates to `make_analysis_app` in `helao/core/drivers/data/analysis_driver.py`, which reads the keys below. `docs/config-schema.md` also lists them.

| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `analyses` | no | list[str] | `[]` | Entries of the form `module` or `module:ClassName`. Each is imported from the deployment's analyses package (`servers.analysis.analyses`, falling back to `drivers.data.analyses`) and exposed as endpoint `analyze_<module>`. Without `:ClassName` the module must hold exactly one `BaseAnalysis` subclass. Any entry that fails to load aborts the server. | `helao/core/drivers/data/analysis_driver.py:1388`, `:282` |
| `env_file` | no | str (path) | `world_cfg.helao_credentials_path`, else env `HELAO_CREDENTIALS`, else `thisfiledoesntexist.env` | Credentials `.env` file passed to `HelaoLoader` for the S3 connection. | `helao/core/drivers/data/analysis_driver.py:516` |
| `max_tasks` | no | int | `1` | Number of concurrent worker coroutines. | `helao/core/drivers/data/analysis_driver.py:523` |
| `local_only` | no | bool | `False` | When true, outputs are written locally and nothing is uploaded to S3. | `helao/core/drivers/data/analysis_driver.py:1237` |
| `analysis_recovery_on_startup` | no | bool | `True` | Sweep the pending-request journal (`<STATES>/ana_pending`) at startup. | `helao/core/drivers/data/analysis_driver.py:1507` |
| `analysis_recovery_max_per_startup` | no | int | `250` | Entries re-enqueued per sweep batch; non-integer values fall back to 250. A value `<= 0` becomes 0, which removes the cap (`:793`, `:812`). | `helao/core/drivers/data/analysis_driver.py:787` |
| `analysis_recovery_drain_when_idle` | no | bool | `True` | Keep draining the journal in slices while the server is idle. | `helao/core/drivers/data/analysis_driver.py:1519` |
| `analysis_recovery_idle_poll_seconds` | no | float | `30` | Idle-check interval for that drain; floored at 1 second. | `helao/core/drivers/data/analysis_driver.py:935` |

The analysis modules in `analyses/` (`uvis_bkgsubnorm.py`, `echeuvis_stability.py`) read no server params. They take per-call analysis parameters instead.

Example:
```yaml
params:
  local_only: false
  analyses: [uvis_bkgsubnorm]
```

## Notes

- `analyses` is read in two places (`make_analysis_app` for the endpoints and the journal recovery with the same class map), so a station config needs it set for either to work.
- The `hte` configs only carry this server commented out (`analyses: [icpms_local, xrfs_local]`).
