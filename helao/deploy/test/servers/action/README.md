# action

Two simulated action servers for the `test` deployment: `control_sim` (engineering-control simulator with no hardware) and `sim_db_server` (data-packaging server that hosts the real `NativeSyncer` for golden-master capture).

## Vendor software
No vendor software beyond the env files.

## Params
Host-level keys every server accepts: see `docs/config-schema.md` ("Group conventions for `params:`").

### `control_sim` (`fast:` value)
Which private routes register depends on which keys are present: the digital-output pair needs `dev_do`, the motion trio needs `axis_id`.

| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `dev_do` | no | dict `{do_name: port}` | `{}` | Digital-output lines the server admits. A line whose value is `None` is unreadable: it accepts writes and always reads back unknown. Other values are not used. | `helao/deploy/test/servers/action/control_sim.py:100`, `:114` |
| `axis_id` | no | dict `{axis: controller_letter}` | `{}` | Movable axes. | `helao/deploy/test/servers/action/control_sim.py:101` |
| `count_to_mm` | no | dict `{controller_letter: mm_per_count}` | `{}` | Scale per controller letter (the `letter_scale` schema). An axis without a scale reports no mm conversion. | `helao/deploy/test/servers/action/control_sim.py:102`, `:129` |

Example (from `controlneg.yml`):
```yaml
params:
  dev_do:
    gamry_aux: 1
    unreadable_line: null
```
```yaml
params:
  axis_id: {x: A, y: B}
  count_to_mm: {A: 0.00015628, B: 0.00015628}
```

### `sim_db_server` (`fast:` value)
Builds a `NativeSyncer`, so it reads the same keys as the `SYNC` server. Those are in `docs/config-schema.md` ("Group conventions for `params:`", the `SYNC` table). The test configs set `aws_bucket` and no `aws_config_path`, so the syncer has no S3 client (local-only sync) unless `s3_record` is set. One key is specific to this server:

| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `s3_record` | no | bool | `False` | `True`: swap in a recording S3 client that writes every upload to `<root>/S3_SIM/<bucket>/<key>` and logs a manifest line. | `helao/deploy/test/servers/action/sim_db_server.py:86` |
| `aws_bucket` | yes | string | none | Needed by `NativeSyncer` (see the `SYNC` table). | `helao/hexagon/adapters/native/sync_driver.py:1289` |

Example (from `golden.yml`):
```yaml
params:
  aws_bucket: helao-sim
  s3_record: true
```

Notes:
- `NativeSyncer` replaces its params with those of the server keyed `SYNC` when its own params carry no `aws_config_path` (`helao/hexagon/adapters/native/native_syncer.py:48`). `s3_record` is read after that, so a `sim_db_server` that is not itself keyed `SYNC`, in a config that also has a `SYNC` server, reads `s3_record` from that other server's params. The test configs key it `SYNC`.
