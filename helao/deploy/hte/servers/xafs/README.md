# xafs

easyXAFS spectrometer action server (`xafs_server`): runs wafer-grid XAFS scans by driving a separate sidecar process over loopback HTTP. The sidecar (`sidecar/xafs_sidecar.py`, Python 3.9) owns the hardware and the vendor `easyxafs` package. `driver.py` is the HTTP client (`XafsSidecarDriver`). `naming.py` builds savenames and applies the plate-to-stage affine.

## Vendor software
The sidecar needs packages that no env file installs. It runs in its own Python 3.9 environment, not the `helao` env.

- `easyxafs`: the instrument's vendor package (modules `ketek`, `monochromator`, `scan`, `wafer_stage_motor_control`, `xchanger_control`). Take it from the instrument computer's easyxafs checkout. The code and docs do not say where else it is distributed.
- `pyprotohv`: imported by `sidecar/runner.py` (and named in `sidecar/hardware.py`). Source not documented; take it from the instrument computer's easyxafs environment.
- `easyxafs_xray_utils` 1.1.0 (wheel) and the `hklhop` package: per `sidecar/environment-sim.yml`, both come from the instrument's easyxafs environment; `hklhop` is not on PyPI (copy its directory into the env's `site-packages`).
- For the simulator (`simulate: true`): `sidecar/environment-sim.yml` creates the Python 3.9 conda env `easyxafs-sim`. After `conda env create`, install the `easyxafs_xray_utils` wheel, copy `hklhop`, and make the `easyxafs` checkout importable with a `.pth` file in the env's `site-packages` (steps are in the comments of that file). The simulator stubs the vendor hardware modules, so no device drivers are needed.
- Hardware SDKs behind `easyxafs` (monochromator, KETEK detector, wafer stage, X-changer) are not referenced by this repo's code. If they need separate vendor installers, that is not documented here.

## Params
Host-level keys every server accepts: see `docs/config-schema.md` ("Group conventions for `params:`").

### `xafs_server` (`fast:` value)
| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `sidecar_port` | yes | int | none | TCP port of the sidecar HTTP API. `connect()` fails with "missing sidecar_port in config" if absent. | `helao/deploy/hte/servers/xafs/driver.py:54`, `:139` |
| `sidecar_host` | no | string | `"127.0.0.1"` | Host the driver calls. The sidecar itself always binds `127.0.0.1`. | `helao/deploy/hte/servers/xafs/driver.py:58` |
| `spawn_sidecar` | no | bool | `False` | `True`: if `/health` does not answer, start the sidecar subprocess and wait for it; the driver shuts down a sidecar it spawned on disconnect. `False`: connect fails if the sidecar is not already running. | `helao/deploy/hte/servers/xafs/driver.py:55`, `:145` |
| `sidecar_python` | when spawning | string | none | Python executable of the sidecar's 3.9 env. Missing: the spawn fails ("could not spawn sidecar"). | `helao/deploy/hte/servers/xafs/driver.py:155` |
| `sidecar_script` | when spawning | string | none | Path of `xafs_sidecar.py`. Missing: the spawn fails. | `helao/deploy/hte/servers/xafs/driver.py:156` |
| `sidecar_args` | no | list of string | `[]` | Extra command-line arguments for the sidecar (it accepts `--simulate`, `--lock-file`, `--state-dir`). | `helao/deploy/hte/servers/xafs/driver.py:149` |
| `simulate` | no | bool | `False` | Adds `--simulate` to a spawned sidecar. On connect, the driver compares it with the running sidecar's `simulate` flag and fails on a mismatch, also for a sidecar that was already running. | `helao/deploy/hte/servers/xafs/driver.py:105`, `:151` |
| `request_timeout` | no | number (s) | `10.0` | Timeout of each HTTP call to the sidecar. | `helao/deploy/hte/servers/xafs/driver.py:56` |
| `spawn_wait_s` | no | number (s) | `30.0` | How long to poll `/health` after spawning before giving up. | `helao/deploy/hte/servers/xafs/driver.py:57` |
| `references` | for `run_use` `izero` / `energy_calib` | dict | `{}` | `{reference_name: {x_mm: float, y_mm: float}}`: stage position of each reference pellet. A `reference_name` not in this dict raises a scan-setup error. | `helao/deploy/hte/servers/xafs/xafs_server.py:153`, `:159` |
| `platexy_to_stage` | for `run_use` `data` | 2x3 list of float | none | Affine matrix `[[a, b, tx], [c, d, ty]]` mapping plate XY (mm) to stage XY (mm). `KeyError` on the first `data` scan if absent. | `helao/deploy/hte/servers/xafs/xafs_server.py:185`, `helao/deploy/hte/servers/xafs/naming.py:27` |

Notes:
- The server sets `allow_concurrent_actions` to `False` in code (`helao/deploy/hte/servers/xafs/xafs_server.py:399`); the config value is overridden.
- `platexy_to_stage` is read for every sample scan but the one existing station config sets none. A `run_use: data` scan with that config fails with `KeyError`. Reported, not changed.

Example:
```yaml
params:
  sidecar_port: 18765
  spawn_sidecar: true
  simulate: false
  sidecar_python: 'C:/Users/<user>/anaconda3/envs/easyxafs_env/python.exe'
  sidecar_script: helao/deploy/hte/servers/xafs/sidecar/xafs_sidecar.py
  references:
    Fe2O3_pellet: {x_mm: 55.4, y_mm: -32.0}
    ZnO_film: {x_mm: 53.9, y_mm: 31.4}
  platexy_to_stage:
    - [1.0, 0.0, 0.0]
    - [0.0, 1.0, 0.0]
```

Unused keys seen in configs: `save_root` (no code in this folder reads it; the sequence library takes `save_root` as a sequence param).
