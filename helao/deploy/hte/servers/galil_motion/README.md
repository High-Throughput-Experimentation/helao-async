# galil_motion

Action server for Galil-controlled motion stages (`galil_motion.py`, backed by `NativeGalilMotion` in `galil_motion_native.py`): axis moves and queries, plate-alignment and coordinate transforms, and an optional Bokeh plate aligner (`galil_aligner_host.py`).

## Vendor software

Install by hand (not pip/conda), on Windows or Linux:

1. The Galil gclib C library: the vendor installer on Windows, the Galil package
   repository on Linux (https://www.galil.com/sw/pub/all/doc/gclib/html/).
2. One gclib Python wrapper. Both install as `import gclib`, so an env holds one,
   and the server's `gclib_api` param must match it:
   - `gclib_api: "1"` (default): wrapper 1.0.1, the `gclib.py()` API, from the
     gclib installation's Python wrapper (gclib 2.4.1 Python docs). From the
     helao env on Windows:
     `python "C:\Program Files (x86)\Galil\gclib\source\wrappers\python\setup.py" install`.
     On Linux, run the same `setup.py install` from the `wrappers/python` folder
     of the gclib installation. Alternative (`setup.py install` is deprecated
     in current setuptools): `python -m pip install "<gclib install>/source/wrappers/python"`.
   - `gclib_api: "2"`: wrapper 2.x, the `gclib.Controller` API (Python >= 3.12):
     `pip install --upgrade --index-url https://www.galil.com/sw/pub/python gclib`
     (docs: https://www.galil.com/sw/pub/python/doc/index.html).
     Not yet verified at a station (reply trimming, gcaps bypass, unsolicited
     output without `-s ALL`): before using `"2"` in production, run
     `helao/deploy/hte/tests/smoke/golden_capture_galil.py` and
     `golden_capture_galil_io.py` with `"1"` and with `"2"` and diff the captures.

A mismatch fails at connect with a message naming `gclib_api`.

## Params

Host-level keys every server accepts: see docs/config-schema.md ("Group conventions for `params:`").

### `galil_motion` (`fast:`)

Read by `galil_motion.py` (the server), `NativeGalilMotion` (the driver, constructed with `config=server_params`), `GalilAlignerHost`, and the Bokeh aligner layout.

| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `galil_ip_str` | yes in practice | str | `None` | Controller IP. When empty or absent, `connect` leaves the driver `uninitialized` and the motion endpoints are not registered. Opened as `"<ip> --direct -s ALL"`. | `helao/deploy/hte/servers/galil_motion/galil_motion_native.py:162` |
| `axis_id` | yes in practice | dict[str, str] | `{}` | Map of HELAO axis name to Galil axis letter, for example `{x: B, y: A}` or `{x: C, y: B, z: A, Rz: D}`. When empty, no motion endpoints are registered. | `helao/deploy/hte/servers/galil_motion/galil_motion_native.py:106`, `helao/deploy/hte/servers/galil_motion/galil_motion.py:126` |
| `count_to_mm` | no | dict[str, float] | `{}` | Millimetres per encoder count, keyed by Galil axis letter. A missing letter reads as 0 in `query_axis_position`, as `None` in the counts query, and raises `KeyError` in a move. | `helao/deploy/hte/servers/galil_motion/galil_motion_native.py:308`, `:366`, `:593`, `:622` |
| `axis_zero` | no (required by `setmotionref`) | dict[str, float] | none (KeyError) | Zero position in mm, keyed by Galil axis letter. Read only by the `setmotionref` homing sequence. | `helao/deploy/hte/servers/galil_motion/galil_motion_native.py:768` |
| `timeout` | no | number (s) | `60` | Motor move timeout. | `helao/deploy/hte/servers/galil_motion/galil_motion_native.py:118` |
| `max_speed_count_sec` | no | int | `25000` | Maximum speed in counts per second; move speeds are clamped to it. | `helao/deploy/hte/servers/galil_motion/galil_motion_native.py:119` |
| `def_speed_count_sec` | no | int | `10000` | Default speed in counts per second. | `helao/deploy/hte/servers/galil_motion/galil_motion_native.py:122` |
| `M_instr` | no | 4x4 list of numbers | identity matrix | Instrument transform used when no instrument calibration file is found. Logs a warning when neither exists. | `helao/deploy/hte/servers/galil_motion/galil_motion_native.py:231`, `:238` |
| `z_height_mm` | no | dict[str, float] | `{}` | Named z heights in mm. Each key becomes a `z_position` choice of the `z_move` action; the server adds a `NA` key (no-op). Only read when `axis_id` is non-empty. | `helao/deploy/hte/servers/galil_motion/galil_motion.py:590` |
| `enable_aligner` | no | bool | `False` | Start the Bokeh plate aligner (`/Aligner`) when the controller connected. | `helao/deploy/hte/servers/galil_motion/galil_motion.py:110` |
| `bokeh_port` | no | int or null | `port + 1000` of the server block | Port of the aligner Bokeh server. Null counts as unset. | `helao/hexagon/preflight.py:109` (used by `galil_aligner_host.py:163`) |
| `cutoff` | no | number | `6` | Aligner layout cutoff value, wrapped in `np.array`. | `helao/deploy/hte/layouts/aligner.py:129` |
| `gclib_api` | no | str `"1"` or `"2"` (YAML int `1`/`2` accepted) | `"1"` | Which gclib Python wrapper API the env holds (see Vendor software). Any other value raises `ValueError` at driver construction. | `helao/deploy/hte/servers/galil_motion/galil_channels.py:25` |

Example:
```yaml
params:
  galil_ip_str: 192.168.x.x
  gclib_api: "1"
  enable_aligner: true
  bokeh_port: 5003
  axis_id:
    x: B
    y: A
  count_to_mm:
    A: 0.00015625
    B: 0.00015625
  axis_zero:
    A: 127.8
    B: 76.7
  def_speed_count_sec: 10000
  max_speed_count_sec: 25000
  timeout: 600
  M_instr:
    - [1, 0, 0, 0]
    - [0, 1, 0, 0]
    - [0, 0, 1, 0]
    - [0, 0, 0, 1]
```

## Notes

- `GalilCommandChannel` tests use `tests/fake_gclib.py`, so no gclib install is needed to run them.
