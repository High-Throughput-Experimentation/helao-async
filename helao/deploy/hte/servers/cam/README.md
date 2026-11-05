# cam

Action server for an Axis IP camera. It starts and cancels an image-stream acquisition (`acquire_image`, `cancel_acquire_image`).

## Vendor software

No vendor software beyond the env files. The camera is read over HTTP (`requests`); it needs a reachable Axis camera serving `/jpg/1/image.jpg`.

## Params

Host-level keys every server accepts: see docs/config-schema.md ("Group conventions for `params:`").

### `cam_server` (`fast:`)

| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `axis_ip` | yes | str | none (KeyError if absent) | IP address or hostname of the Axis camera. Images are fetched from `http://<axis_ip>/jpg/1/image.jpg`. | `helao/deploy/hte/servers/cam/axiscam_driver.py:51`, `:53` |

Example:
```yaml
params:
  axis_ip: 192.168.x.x
```
