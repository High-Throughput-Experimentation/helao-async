# visualizer

Bokeh apps and panels shared by every `hte` station: the three visualizer hosts (`action_visualizer`, `live_visualizer`, `control_visualizer`), the data browser (`data_browser`), and the per-server control and live panels they mount.

## Vendor software
No vendor software beyond the env files.

## Params
Host-level keys every server accepts: see `docs/config-schema.md` ("Group conventions for `params:`").

Two kinds of params apply here. Keys of a visualizer host's own `params:` are set on the `group: visualizer` server that runs the app. Keys read from a controlled or monitored server's `params:` are set on that action server (the one whose config names the panel with `action_vis`, `live_vis` or `control_vis`).

### Visualizer host (`action_visualizer`, `live_visualizer`, `control_visualizer`; `bokeh:` value)
Read from the host server's own `params:`. The `group: visualizer` table in `docs/config-schema.md` lists the keys; code behind each:

| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `limit_vis` | no | list of string (or string) | `[]` | Only the listed action-server keys get panels. A bare string is tested as a substring of the server key; write a list. | `helao/ui/bokeh/vis_subscriber.py:111`, `:119` |
| `update_rate` | no | number (s) | `0.001` (action), `0.5` (live) | Minimum seconds between WebSocket reads of each mounted panel. | `helao/ui/bokeh/vis_subscriber.py:387` (action), `:373` (live), `:215` |

Each host mounts the panel named by one key of the monitored server: `action_visualizer` mounts `action_vis`, `live_visualizer` mounts `live_vis`, `control_visualizer` mounts `control_vis` (`helao/deploy/hte/servers/visualizer/_vis_host.py:51`).

### `data_browser` (`bokeh:` value)
| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `max_points` | no | int | `50000` | Trailing-window size of a plotted trace. | `helao/ui/bokeh/data_browser.py:62` |

### Control panels: params read from the controlled server
These modules read no host params. Each one reads keys from the `params:` of the action server that declares it with `control_vis`.

| module | reads from the controlled server | meaning | read at |
|---|---|---|---|
| `digital_out_control` | `dev_do` (dict) | One toggle per key. A name in two groups gets no second control. | `helao/ui/shared/io_control.py:98`, `:102` |
| `motion_control_letter_scale` | `axis_id` (`{axis: controller letter}`), `count_to_mm` (`{letter: mm per count}`) | One row per `axis_id` key; scale looked up by the letter. | `helao/ui/shared/motion_control.py:236`, `:293` |
| `motion_control_name_scale` | `axis_id` (`{axis: serial number}`), `count_to_mm` (`{axis: mm per count}`) | One row per `axis_id` key; scale looked up by the axis name. No `hte` station config uses it. | `helao/ui/shared/motion_control.py:236`, `:298` |
| `motion_control_inverse_scale` | `axes` (`{axis: {pos_scale: counts per mm, move_limit_mm: float, ...}}`) | One row per `axes` key; scale is `1 / pos_scale`. A missing, zero or non-finite `pos_scale` leaves the axis without a scale. | `helao/ui/shared/motion_control.py:238`, `:300` |

All three motion panels also read an optional `warn_above_mm` (`{axis: mm}`) from the controlled server: a move longer than this asks for confirmation. Order: `warn_above_mm[axis]`, then `axes[axis].move_limit_mm`, then the default `10.0` mm. A value that is not positive and finite is skipped (`helao/ui/shared/motion_control.py:98`, `:356`).

### Live panels: params read from the monitored server
| module | reads from the monitored server | meaning | read at |
|---|---|---|---|
| `pressure_vis` (`action_vis` / `live_vis`) | `dev_ai` (dict) | Sorted keys are the analog-input channels plotted and tabled. | `helao/deploy/hte/servers/visualizer/pressure_vis.py:62` |
| `temp_vis` (`action_vis` / `live_vis`) | `dev_monitor` (dict) | Sorted keys are the temperature channels plotted. | `helao/deploy/hte/servers/visualizer/temp_vis.py:50` |

`_vis_host.py` and `_live_panel.py` are helpers and read no params.

Example (visualizer host, then a motion server it controls):
```yaml
VIS_CONTROL:
  group: visualizer
  bokeh: control_visualizer
  params:
    doc_name: Engineering Controls
    limit_vis: [MOTOR]
MOTOR:
  group: action
  control_vis: motion_control_letter_scale
  params:
    axis_id: {x: C, y: B, z: A}
    count_to_mm: {C: 1.5628e-04, B: 1.5628e-04, A: 1.5628e-04}
    warn_above_mm: {z: 5.0}
```
