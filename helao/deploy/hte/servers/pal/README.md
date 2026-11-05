# pal

Action server for a PAL autosampler (liquid and gas transfers, GC/HPLC injections, archive, deep clean). It builds `.cam` method jobs and runs the PAL program locally or over SSH, optionally synchronised by NI-DAQmx digital-input triggers. See `CLAUDE.md` in this folder for how the SSH identity is configured.

## Vendor software

Install by hand (not pip/conda):

- PAL autosampler control software, providing the `PAL` command-line program and the `.cam` methods. The driver runs `PAL <jobfile> /start /quit` (`pal_transport.py:136`), either on this machine (`host: localhost`) or, over SSH, on the PAL PC. The `.cam` method files named under `cams` must exist in `cam_file_path` on the machine where PAL runs. The code does not say where to get the software or which version.
- Remote PAL PC (SSH mode only): an SSH server on a Cygwin install (the driver writes paths as `/cygdrive/c/...`, `pal_transport.py:106`) that accepts the RSA key named by `key`.
- NI-DAQmx driver runtime on the HELAO machine, only when `dev_trigger: NImax` (the `nidaqmx` package, in `requirements.txt`, is imported lazily at `pal_trigger.py:88`). See `../nidaqmx/README.md`.

`paramiko` is in `environment.yml`.

## Params

Host-level keys every server accepts: see docs/config-schema.md ("Group conventions for `params:`").

### `pal_server` (`fast:`)

| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `host` | yes, unless `host_env` is set | str | `None` | SSH hostname of the PAL PC, or `localhost` to run PAL on this machine. A literal value wins over `host_env`. If neither gives a value, `connect()` fails and every PAL action returns `not_available`. | `helao/deploy/hte/servers/pal/pal_driver.py:227`, `pal_driver.py:92` |
| `host_env` | no | str | none | Name of an environment variable holding the host. Unset or empty logs an error. | `pal_driver.py:97` |
| `user` | no | str | `""` | SSH user. Literal value wins over `user_env`. | `pal_driver.py:225` |
| `user_env` | no | str | none | Environment variable holding the SSH user. | `pal_driver.py:97` |
| `key` | no | str | `""` | Path to the RSA private key file used for SSH (`paramiko.RSAKey.from_private_key_file`). Literal value wins over `key_env`. | `pal_driver.py:226`, `pal_transport.py:61` |
| `key_env` | no | str | none | Environment variable holding the key path. | `pal_driver.py:97` |
| `timeout` | no | float (s) | `1800` (`30 * 60`) | Passed to the NI-DAQmx trigger poller as its wait timeout. Not read when `dev_trigger` is not `NImax`. | `pal_driver.py:229`, `pal_driver.py:255` |
| `dev_trigger` | no | str | `None` | `NImax` selects the NI-DAQmx digital-input trigger handshake; any other value (or absent) uses a no-op trigger. | `pal_driver.py:242` |
| `trigger` | yes if `dev_trigger: NImax` | dict | none | Indexed without a default (`KeyError` if absent). Keys `start`, `continue`, `done`: NI-DAQmx digital-input lines (e.g. `PXI-6284/port2/line5`); each defaults to `None` when omitted. | `pal_driver.py:245` |
| `cam_file_path` | no | str | `""`, then `None` | Directory holding the `.cam` files on the PAL machine. Re-read at `pal_driver.py:298` with default `None`, which is the value in effect. | `pal_driver.py:228`, `pal_driver.py:298` |
| `cams` | no | dict `{cam_name: file_name}` | `None` | Maps a method name from the `CAMS` enum (`enum.py:38`: `transfer_tray_tray`, `transfer_custom_tray`, `transfer_tray_custom`, `transfer_custom_custom`, `injection_custom_GC_gas_wait`, `injection_custom_GC_gas_start`, `injection_custom_GC_liquid_wait`, `injection_custom_GC_liquid_start`, `injection_tray_GC_liquid_wait`, `injection_tray_GC_liquid_start`, `injection_tray_GC_gas_wait`, `injection_tray_GC_gas_start`, `injection_custom_HPLC`, `injection_tray_HPLC`, `deepclean`, `none`, `archive`) to its `.cam` file name. A name left out gets file name `None` and its actions return `not_available`. With no `cams` key at all, every method is unavailable. | `pal_driver.py:297`, `pal_server.py:111` |
| `positions` | no | dict | none | Only `positions.custom` is read here: its keys become the `dev_custom` enum of the custom-position endpoints. Sample-archive positions normally live on the SAMPLE server (see docs/config-schema.md). | `pal_server.py:115` |
| `world_config` | no | dict | `config_loader.CONFIG`, else `{}` | Overrides the world config handed to the sample-archive shim, which resolves the SAMPLE server's host and port from it. Station configs do not set it. | `pal_driver.py:215` |

Example (adapted from a station config; SSH identity by environment variable):
```yaml
params:
  user_env: HELAO_PAL_SSH_USER
  key_env: HELAO_PAL_SSH_KEY
  host_env: HELAO_PAL_SSH_HOST
  timeout: 1800
  dev_trigger: NImax
  trigger:
    start: PXI-6284/port2/line5
    continue: PXI-6284/port2/line7
    done: PXI-6284/port2/line3
  cam_file_path: C:\Users\<user>\Desktop\psc_methods\HELAO
  cams:
    transfer_tray_tray: tray_to_tray_220214.cam
    transfer_custom_tray: custom_to_tray_220214.cam
    archive: custom_to_tray_220214.cam
    deepclean: deep_clean_220214.cam
```

Local mode (PAL on the HELAO machine) uses `host: localhost` and needs no `user`/`key`.

Notes:
- The PAL server needs a `SAMPLE` server in the same config: the sample-archive shim looks up `world_cfg["servers"]["SAMPLE"]` for host and port (`sample_shim.py:190`).
- `cam_file_path` is read twice with defaults `""` and `None` (`pal_driver.py:228`, `pal_driver.py:298`); only the second value reaches the `cams` table.
