# reflex

Reflex panel modules for the `hte` deployment: the Reflex counterparts of the Bokeh panels in `../visualizer/`. They answer to the same `action_vis` / `live_vis` / `control_vis` keys. A station gains them by adding a `reflex:` server entry; no per-server config change is needed.

## Vendor software
No vendor software beyond the env files.

## Params
Host-level keys every server accepts: see `docs/config-schema.md` ("Group conventions for `params:`"). The keys of the `reflex:` server itself (`limit_vis`, `pages`, `retire`, ...) are in the `group: visualizer` table of that file and in its "Reflex UI pages" section.

The modules here read no params of the `reflex:` server. They read two things from the config:

- the `host` and `port` of the monitored or controlled action server (`helao/deploy/hte/servers/reflex/_pstat.py:172`, `helao/deploy/hte/servers/reflex/_pstat_panel.py:138`, `helao/deploy/hte/servers/sample/reflex/sample_vis.py:109`);
- for the control panels, keys of that action server's `params:`, through the same shared code as the Bokeh panels.

### Control panels: params read from the controlled server
| module (`control_vis`) | reads from the controlled server | meaning | read at |
|---|---|---|---|
| `digital_out_control` | `dev_do` (dict) | One control per key. | `helao/ui/shared/io_control.py:98`, `:102` |
| `motion_control_letter_scale` | `axis_id` (`{axis: controller letter}`), `count_to_mm` (`{letter: mm per count}`) | One row per `axis_id` key. | `helao/ui/shared/motion_control.py:236`, `:293` |
| `motion_control_name_scale` | `axis_id` (`{axis: serial number}`), `count_to_mm` (`{axis: mm per count}`) | One row per `axis_id` key. No `hte` station config uses it. | `helao/ui/shared/motion_control.py:236`, `:298` |
| `motion_control_inverse_scale` | `axes` (`{axis: {pos_scale: counts per mm, move_limit_mm: float, ...}}`) | One row per `axes` key; scale is `1 / pos_scale`. | `helao/ui/shared/motion_control.py:238`, `:300` |

The three motion panels also read an optional `warn_above_mm` (`{axis: mm}`): a move longer than this asks for confirmation. Order: `warn_above_mm[axis]`, then `axes[axis].move_limit_mm`, then the default `10.0` mm (`helao/ui/shared/motion_control.py:98`, `:356`).

### Live and action panels
`pressure_vis` and `temp_vis` (`live_vis`) read no params: they plot every column the server streams, unlike the Bokeh versions, which take their channels from `dev_ai` and `dev_monitor`. `_live.py`, `_action.py`, `_pstat.py`, `_pstat_panel.py`, `_samples.py` and `_spectra.py` are shared helpers and read no params.

Example (the `reflex:` server and a motion server it controls):
```yaml
UI:
  group: visualizer
  reflex: helao_ui
  params:
    limit_vis: [MOTOR]
MOTOR:
  group: action
  control_vis: motion_control_letter_scale
  params:
    axis_id: {x: C, y: B, z: A}
    count_to_mm: {C: 1.5628e-04, B: 1.5628e-04, A: 1.5628e-04}
```
