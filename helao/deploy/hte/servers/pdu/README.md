# pdu

Action server for a Synaccess Netbooter power distribution unit: switches outlets on and off over the unit's `cmd.cgi` HTTP interface.

## Vendor software

No vendor software beyond the env files. The driver talks plain HTTP to the PDU with `httpx`.

## Params

Host-level keys every server accepts: see docs/config-schema.md ("Group conventions for `params:`").

### `pdu_server` (`fast:`)

Missing required keys do not stop the server: the driver logs an error and every outlet command then returns a failed response (`helao/deploy/hte/servers/pdu/driver.py:71`).

| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `hostname` | yes | str | `None` | PDU host or IP; commands go to `http://<hostname>/cmd.cgi?`. | `helao/deploy/hte/servers/pdu/driver.py:57` |
| `username` | yes | str | `None` | HTTP basic-auth user. | `driver.py:58` |
| `password` | yes, unless `password_env` is set | str | `None` | HTTP basic-auth password. Wins over `password_env` when both are set. | `driver.py:59` |
| `password_env` | no | str | `None` | Name of an environment variable holding the password. Consulted only when `password` is absent; an unset or empty variable counts as a missing password. | `driver.py:60` |
| `timeout` | no | float (s) | `5.0` | Per-request HTTP timeout. | `driver.py:82` |
| `retry_delay` | no | float (s) | `0.5` | Delay between retry attempts of one command. | `driver.py:67` |

Example (keep the password out of the config; use `password_env`):
```yaml
params:
  hostname: 192.168.x.x
  username: <user>
  password_env: HELAO_PDU_PASSWORD
```
