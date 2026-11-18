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

## Outputs

### `control_sim` (entry point: `makeApp`)

No data files or action results. Its endpoints are `tags=["private"]` routes that return values to the caller (`helao/deploy/test/servers/action/control_sim.py:182`, `:193`, `:211`, `:231`, `:273`); it registers no data-writing action.

### `sim_db_server` (entry point: `makeApp`)

Registers no data-writing action and sets no action results. It hosts the framework syncer (`SimNativeSyncer`, `helao/deploy/test/servers/action/sim_db_server.py:81-88`, wired as the driver at `:99`), which writes the first two files below. They are framework outputs, documented in `helao/hexagon/adapters/native/CLAUDE.md` and `docs/superpowers/specs/2026-10-23-json-storage-format-design.md`, and are not catalogued field by field here.

| file | format | name pattern | meaning | written at |
|---|---|---|---|---|
| `.prg` | YAML | beside each record, `<record>.prg` | sync progress sidecar of one record | `helao/hexagon/adapters/native/sync_driver.py:1097` |
| `-prc.json` | JSON | `<pidx>__<uuid>__<technique_name>-prc.json` in the experiment's directory | process record pushed to S3 and the API | `helao/hexagon/adapters/native/sync_driver.py:2608` |

The rest of this section covers the recorder, active only with `s3_record: true`. It records every S3 upload the syncer would make to the local tree `<root>/S3_SIM`; the content is whatever the syncer uploads (the record's own file list, see `helao/hexagon/adapters/native/CLAUDE.md`).

| file | format | name pattern | meaning | written at |
|---|---|---|---|---|
| uploaded object copy | as uploaded (not interpreted) | `<root>/S3_SIM/<bucket>/<key>` | copy of the object passed to `upload_fileobj` | `helao/deploy/test/servers/action/sim_db_server.py:68-71` |
| uploaded object copy | as uploaded (not interpreted) | `<root>/S3_SIM/<bucket>/<key>` | copy of the file passed to `upload_file` | `helao/deploy/test/servers/action/sim_db_server.py:75-77` |
| `manifest.jsonl` | JSON lines | `<root>/S3_SIM/manifest.jsonl` | one line per upload (below) | `helao/deploy/test/servers/action/sim_db_server.py:64-65` |

Manifest line (built at `helao/deploy/test/servers/action/sim_db_server.py:57-62`):

| field | type | structure | meaning |
|---|---|---|---|
| `bucket` | str | scalar per row | S3 bucket argument |
| `key` | str | scalar per row | S3 key argument |
| `mode` | str | scalar per row | `"fileobj"` or `"file"` |
| `gzip` | bool | scalar per row | `key` ends with `.gz` |
