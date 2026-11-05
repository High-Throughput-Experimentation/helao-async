# sync

Data syncer action server (`sync_server`): hosts `NativeSyncer`, which uploads finished action, experiment and sequence records to S3 and runs the post-finish hooks. Syncer internals: `helao/hexagon/adapters/native/CLAUDE.md`.

## Vendor software
No vendor software beyond the env files. S3 credentials come from an INI file named by the `AWS_CONFIG_PATH` environment variable (see `aws_profile` below).

## Params
Host-level keys every server accepts: see `docs/config-schema.md` ("Group conventions for `params:`").

The `SYNC` params table (`aws_profile`, `aws_config_path`, `aws_bucket`, `max_tasks`, `sync_pending_on_startup`, `quarantine_strikes`, `quarantine_hours`, `testing`) is in `docs/config-schema.md`, section "Group conventions for `params:`" under `group: action`. Not repeated here. Post-finish hooks are a server-level `postfinish_hooks` key, not a param (see "Finish hooks" in the same file).

Keys that table does not list:

### `sync_server` (`fast:` value)
| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `aws_access_key_id` | only when `params` sets `aws_config_path` and no INI profile supplies it | string | none | Inline credential. Read when `aws_config_path` ends up in the merged config (from an INI profile, or set in `params`); then `KeyError` if missing. | `helao/hexagon/adapters/native/sync_driver.py:1279` |
| `aws_secret_access_key` | as above | string | none | Inline credential; same condition. Do not commit it. | `helao/hexagon/adapters/native/sync_driver.py:1280` |
| `region` | as above | string | none | AWS region; same condition. | `helao/hexagon/adapters/native/sync_driver.py:1281` |

The INI profile named by `aws_profile` supplies these three keys and `aws_bucket` when `AWS_CONFIG_PATH` is set.

Example (as used by the `hte` configs):
```yaml
params:
  aws_profile: default
```
