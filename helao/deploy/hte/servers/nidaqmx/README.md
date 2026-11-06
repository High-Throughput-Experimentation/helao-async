# nidaqmx

Action server for National Instruments DAQmx hardware: digital outputs (cells, pumps, valves, LEDs, heaters, TTL), foot-switch digital inputs, thermocouple monitoring, a heater loop, and synchronised multi-cell current/voltage measurement.

## Vendor software

Install by hand (not pip/conda):

- NI-DAQmx driver runtime. The `nidaqmx` Python package (in `requirements.txt`) only wraps it and does not work without it. The code does not say where to download it; National Instruments distributes it.

## Params

Host-level keys every server accepts: see docs/config-schema.md ("Group conventions for `params:`").

### `nidaqmx_server` (`fast:`)

Every key is optional. An endpoint is registered only when its group is non-empty. The `nidaqmx_control` and `nidaqmx_vis` panels (`control_vis:` / `action_vis:`) read no params of their own; the control panels take the digital-output group list from `DO_GROUPS` in `nidaqmx_server.py`.

Port strings are NI-DAQmx physical channel names, e.g. `cDAQ1Mod1/port0/line9` or `PXI-6289/ai16`.

| key | req | type | default | meaning / allowed values | read at |
|---|---|---|---|---|---|
| `dev_mastercell` | no | dict `{name: do_port}` | `{}` | Digital outputs for the `mastercell` action. | `helao/deploy/hte/servers/nidaqmx/nidaqmx_server.py:247` |
| `dev_activecell` | no | dict `{name: do_port}` | `{}` | Digital outputs for the `activecell` action. | `nidaqmx_server.py:243` |
| `dev_pump` | no | dict `{name: do_port}` | `{}` | Digital outputs for the `pump` action. Also driven low on E-STOP. | `nidaqmx_server.py:216`, `nidaqmx_driver.py:119` |
| `dev_gasvalve` | no | dict `{name: do_port}` | `{}` | Digital outputs for the `gasvalve` action. Also driven low on E-STOP. | `nidaqmx_server.py:219`, `nidaqmx_driver.py:124` |
| `dev_liquidvalve` | no | dict `{name: do_port}` | `{}` | Digital outputs for the `liquidvalve` action. Also driven low on E-STOP. | `nidaqmx_server.py:224`, `nidaqmx_driver.py:129` |
| `dev_multivalve` | no | dict `{name: do_port}` | `{}` | Digital outputs for the `multivalve` action. Not driven low on E-STOP. | `nidaqmx_server.py:229` |
| `dev_led` | no | dict `{name: do_port}` | `{}` | Digital outputs for the `led` action. Also driven low on E-STOP. | `nidaqmx_server.py:234`, `nidaqmx_driver.py:138` |
| `dev_fswbcd` | no | dict `{name: do_port}` | `{}` | Digital outputs for the `fswbcd` action. Not driven low on E-STOP. | `nidaqmx_server.py:237` |
| `dev_heat` | no | dict `{name: do_port}` | `{}` | Digital outputs for the `heater` action and the heater loop. The loop acts only on the names `cellheater` and `res_heater`. Also driven low on E-STOP. | `nidaqmx_server.py:213`, `nidaqmx_driver.py:133`, `nidaqmx_driver.py:658` |
| `dev_ttl` | no | dict `{name: do_port}` | `{}` | TTL lines held high for a duration by the `toggle_ttl` action. Also driven low on E-STOP. | `nidaqmx_server.py:251`, `nidaqmx_driver.py:141` |
| `dev_fsw` | no | dict `{name: di_port}` | `{}` | Digital inputs read by the `fsw` (foot switch) action. | `nidaqmx_server.py:253`, `nidaqmx_server.py:445` |
| `dev_monitor` | no | dict `{name: ai_port}` | `{}` | Thermocouple analog inputs polled continuously. K-type, or T-type when the name contains `Ttc_`; range 0 to 150 degC. The heater loop indexes this dict without a default and reads the names `Ttemp_Ktc_in_cell_C` and `Ttemp_Ttc_in_reservoir_C` (`KeyError` if absent). | `nidaqmx_server.py:210`, `nidaqmx_driver.py:420`, `nidaqmx_driver.py:653` |
| `dev_cellcurrent` | no | dict `{cell: ai_port}` | `{}` | Current analog inputs (master task) for `cellIV`. `cellIV` is registered only when both `dev_cellcurrent` and `dev_cellvoltage` are non-empty; the driver indexes it without a default when a cell IV starts. | `nidaqmx_server.py:239`, `nidaqmx_server.py:457`, `nidaqmx_driver.py:332` |
| `dev_cellvoltage` | no | dict `{cell: ai_port}` | `{}` | Voltage analog inputs (slave task) for `cellIV`. Same registration rule as `dev_cellcurrent`. | `nidaqmx_server.py:241`, `nidaqmx_driver.py:361` |
| `dev_cellcurrent_trigger` | no | str | `""` | Digital-edge start-trigger terminal (e.g. `PFI1`) for the current task. Used only when `TTLwait` is not `-1` and both trigger keys are non-empty; otherwise a warning is logged and the measurement starts without a trigger wait. | `nidaqmx_driver.py:384`, `nidaqmx_driver.py:408` |
| `dev_cellvoltage_trigger` | no | str | `""` | Same, for the voltage task. | `nidaqmx_driver.py:383`, `nidaqmx_driver.py:400` |
| `allow_no_sample` | no | bool | `False` | `True` permits a `cellIV` run with no validated samples. | `nidaqmx_driver.py:143`, `nidaqmx_server.py:504` |
| `do_active_low` | no | list of DO names | `[]` | Names from any DO group (`dev_mastercell`, `dev_activecell`, `dev_pump`, `dev_gasvalve`, `dev_liquidvalve`, `dev_multivalve`, `dev_led`, `dev_fswbcd`, `dev_heat`, `dev_ttl`) wired active-low: logical ON writes LOW, OFF writes HIGH, and readback and `/get_digital_outs` report the logical state. E-STOP still writes OFF, so these lines go HIGH. An unknown name or a non-list raises `ValueError` at start. | `nidaqmx_driver.py:set_digital_out` |
| `do_open_collector` | no | list of DO names, or `true` | `[]` | Lines whose output drive type is set to open collector each time a write or readback task opens them. `true` means every configured DO line. Same validation as `do_active_low`. Some DO modules reject `do_output_drive_type`, so writes to listed lines would then raise; bench-check set OC, write and read on the target module before enabling it on a station. | `nidaqmx_driver.py:set_digital_out` |
| `shutdown_to_off` | no | bool | `False` | `True` writes logical OFF (per-line polarity) to every configured DO line on server shutdown, best effort, before disconnecting. | `nidaqmx_driver.py:async_shutdown` |

Example (digital I/O only, trimmed from a station config):
```yaml
params:
  dev_pump:
    peripump: PXI-6284/port0/line4
    direction: PXI-6284/port0/line0
  dev_gasvalve:
    inlet: PXI-6284/port1/line2
  dev_liquidvalve:
    work_refill: PXI-6284/port1/line4
  dev_fsw:
    done: PXI-6284/port2/line4
  dev_led:
    led: PXI-6289/port0/line0
```

Cell IV and monitor keys, from a station config that uses them:
```yaml
params:
  allow_no_sample: true
  dev_cellcurrent_trigger: PFI1
  dev_cellvoltage_trigger: PFI1
  dev_cellcurrent:
    '1': PXI-6289/ai16
  dev_cellvoltage:
    '1': PXI-6284/ai16
  dev_monitor:
    Ttemp_Ktc_in_cell_C: PXI-6289/ai6
    Ttemp_Ttc_in_reservoir_C: PXI-6289/ai7
```

Notes:
- A name used in more than one digital-output group is logged as an error and refused by the private `set_digital_out` endpoint (`nidaqmx_server.py:121`).
- `dev_pump`, `dev_gasvalve`, `dev_liquidvalve`, `dev_led`, `dev_heat` and `dev_ttl` are read in two places (server and driver) with the same default `{}`.
