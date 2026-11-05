# biologic

Action server for BioLogic potentiostats (`biologic_server.py`). It serves the same technique endpoints (`run_CA`, `run_CP`, `run_CV`, `run_OCV`, `run_PEIS`, `run_GEIS`, and others) from one of three backends chosen by `pstat_backend`: `eclib` (EClib1 DLL, `biologic/`), `olecom` (EC-Lab application over OLE COM, `biologic_ole/`) or `eclib2` (EC-Lib 2.0 SDK, `biologic_eclib2/`). `bokeh/biologic_vis.py` is its action visualizer (`action_vis: biologic_vis`). Design notes for the OLE backend: `CLAUDE.md` in this folder.

## Vendor software

Install by hand (not pip/conda). What a station needs depends on `pstat_backend`; `simulate: true` needs none of it.

- `eclib` (default): the BioLogic EC-Lab Development Package, which provides `EClib64.dll` and the firmware files. Python must be 64-bit. The driver looks in `sdk_path`, default `C:\EC-Lab Development Package\lib` (`biologic/vendor.py:71`, `:73`).
- `olecom`: the EC-Lab application itself, installed and registered for OLE COM (ProgID `EC-Lab.Application`, key `progid`). The driver also needs `comtypes`, which `helao_dev_win-64.yml` installs. The `.mps` templates in `biologic_ole/templates/` are authored in the EC-Lab GUI; see `biologic_ole/templates/README.md`.
- `eclib2`: the BioLogic EC-Lib 2.0 SDK (`biologic_ec_sdk`), unpacked anywhere and named by `sdk_path`. It ships no installable distribution. It must hold `Python/ECLibAPI.py`, `Python/Constants/`, `lib/eclib64.dll` and the license file `license_biologic_*.lic` at its root (`biologic_eclib2/vendor.py:21-26`). Without the license file every call fails with `EC_SDK_ERROR_LICENSE_NOT_VALID` (-99900). EC-Lib 2.0 supports Ethernet only.

The code does not say where BioLogic distributes these packages; get them from BioLogic.

## Params

Host-level keys every server accepts: see docs/config-schema.md ("Group conventions for `params:`").

### `biologic_server` (`fast:`)

| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `pstat_backend` | no | str | `"eclib"` | Backend driver: `"eclib"`, `"olecom"` or `"eclib2"`. Any other value raises `ValueError` when the app is built. | `helao/deploy/hte/servers/biologic/biologic_server.py:1026` |

All other keys are read by the selected backend's driver, below. A key set for another backend is ignored.

### `pstat_backend: eclib`

Driver `biologic/driver.py`.

| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `address` | no | str | `"192.168.200.240"` | Instrument IP passed to the DLL connect. | `helao/deploy/hte/servers/biologic/biologic/driver.py:135` |
| `num_channels` | no | int | `12` | Number of channels the server drives; channel indices run `0..num_channels-1`. | `helao/deploy/hte/servers/biologic/biologic/driver.py:136` |
| `sdk_path` | no | str (path) | `C:\EC-Lab Development Package\lib` | Folder holding `EClib64.dll`, the `.ecc` technique files and firmware. | `helao/deploy/hte/servers/biologic/biologic/driver.py:137` |
| `simulate` | no | bool | `False` | Use the in-process simulator instead of the DLL. | `helao/deploy/hte/servers/biologic/biologic/driver.py:138` |
| `force_load_firmware` | no | bool | `False` | Load the kernel and FPGA firmware at connect even when not needed. | `helao/deploy/hte/servers/biologic/biologic/driver.py:139` |
| `timeout` | no | number (s) | `5` | Connect timeout passed to the client. | `helao/deploy/hte/servers/biologic/biologic/driver.py:140` |

Example:
```yaml
params:
  address: 192.168.x.x
  num_channels: 1
```

### `pstat_backend: olecom`

Driver `biologic_ole/driver.py`.

| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `address` | no | str | `"192.168.200.240"` | Instrument IP passed to EC-Lab's `ConnectDeviceByIP`. | `helao/deploy/hte/servers/biologic/biologic_ole/driver.py:107` |
| `num_channels` | no | int | `12` | Channels this server drives. | `helao/deploy/hte/servers/biologic/biologic_ole/driver.py:108` |
| `simulate` | no | bool | `False` | Use the fake COM server in `sim.py` (no EC-Lab, comtypes or instrument needed). | `helao/deploy/hte/servers/biologic/biologic_ole/driver.py:109` |
| `progid` | no | str | `"EC-Lab.Application"` | EC-Lab OLE ProgID. | `helao/deploy/hte/servers/biologic/biologic_ole/driver.py:110` |
| `com_timeout_s` | no | number (s) | `30.0` | Per-call ceiling on every COM call. | `helao/deploy/hte/servers/biologic/biologic_ole/driver.py:111` |
| `templates_dir` | no | str (path) | `biologic_ole/templates/` in the package | Folder holding the `.mps` templates. | `helao/deploy/hte/servers/biologic/biologic_ole/driver.py:138` |
| `scratch_dir` | no | str (path) | `<cwd>/STATES/olecom` | Where patched settings files and in-progress MPR files are written. | `helao/deploy/hte/servers/biologic/biologic_ole/driver.py:146` |
| `protocol_dir` | no | str (path) | `templates_dir` | Folder `run_protocol` resolves its `mps_path` against; the file must stay inside it. | `helao/deploy/hte/servers/biologic/biologic_ole/driver.py:151` |

Example:
```yaml
params:
  pstat_backend: olecom
  address: 192.168.x.x
  num_channels: 2
  templates_dir: C:\path\to\mps_templates
```

### `pstat_backend: eclib2`

Driver `biologic_eclib2/driver.py`.

| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `address` | yes on a station | str | `""` | Instrument IP (Ethernet only). Unused while simulating. | `helao/deploy/hte/servers/biologic/biologic_eclib2/driver.py:93` |
| `num_channels` | no | int | `1` | Channels this server drives. | `helao/deploy/hte/servers/biologic/biologic_eclib2/driver.py:94` |
| `sdk_path` | yes unless `simulate` | str (path) | `None` | Unpacked `biologic_ec_sdk` root (see Vendor software). Absent with `simulate: false` raises `ValueError("sdk_path is required when simulate is false")`. | `helao/deploy/hte/servers/biologic/biologic_eclib2/driver.py:95`, `helao/deploy/hte/servers/biologic/biologic_eclib2/sdk_client.py:484` |
| `simulate` | no | bool | `False` | Use `biologic_eclib2/sim.py` in place of the SDK. | `helao/deploy/hte/servers/biologic/biologic_eclib2/driver.py:96` |
| `timeout_s` | no | int (s) | `120` | Connect timeout. | `helao/deploy/hte/servers/biologic/biologic_eclib2/driver.py:97` |

Example (simulated, from `helao/deploy/hte/configs/biologiceclib2.yml`):
```yaml
params:
  pstat_backend: eclib2
  simulate: true
  address: 127.0.0.1
  num_channels: 1
```

### `bokeh/biologic_vis.py` (`action_vis: biologic_vis`)

| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `num_channels` | no | int | `1` | Number of channels the visualizer shows. It reads the key from this server's params. | `helao/deploy/hte/servers/biologic/bokeh/biologic_vis.py:99` |

### Unused keys seen in configs

- `allow_no_sample` and `grounded` (set in `hte` configs for this server): no code in this folder reads them.

## Notes

- `num_channels` defaults differ: the `eclib` and `olecom` drivers default to 12, the `eclib2` driver to 1, and the visualizer to 1. A station driving more than one channel on `eclib` or `olecom` without setting the key gets 12 driver channels but a one-channel visualizer.
- The `biologic_ole/driver.py` module docstring says "all optional except `address`", but the code gives `address` a default (`192.168.200.240`) on `eclib` and `olecom`.
- `biologic_server.py:382` writes `server_params["allow_concurrent_actions"] = False` at startup; a config value for it is overwritten.
