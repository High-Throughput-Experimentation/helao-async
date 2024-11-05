# helao.drivers.mfc package

## Submodules

## helao.drivers.mfc.alicat_driver module

A device class for the AliCat mass flow controller.

This device class uses the python implementation from [https://github.com/numat/alicat](https://github.com/numat/alicat)
and additional methods from [https://documents.alicat.com/Alicat-Serial-Primer.pdf](https://documents.alicat.com/Alicat-Serial-Primer.pdf). The 
default gas list included in the module code differs from our MFC at G16 (i-C4H10),
G25 (He-25), and G26 (He-75). Update the gas list registers in case any of the 3 gases 
are used.

NOTE: Factory default control setpoint is analog and must be changed for driver operation.
Setpoint setup (Menu-Control-Setpoint_setup-Setpoint_source) has to be set to serial.

### *class* helao.drivers.mfc.alicat_driver.AliCatMFC(action_serv)

Bases: `object`

#### \_\_init_\_(action_serv)

#### *async* async_shutdown()

Await tasks prior to driver shutdown.

#### *async* estop(\*args, \*\*kwargs)

#### *async* hold_cancel(device_name=None)

Cancel the valve hold.

#### *async* hold_valve(device_name=None)

Hold the valve in its current position.

#### *async* hold_valve_closed(device_name=None)

Close valve and hold.

#### list_gases(device_name)

#### *async* lock_display(device_name=None)

Lock the front display.

#### make_fc_instance(device_name, device_config)

#### manual_query_status(device_name)

#### *async* poll_sensor_loop(waittime=0.1)

#### *async* poll_signal_loop()

#### *async* set_flowrate(device_name, flowrate_sccm, ramp_sccm_sec=0, \*args, \*\*kwargs)

Set control mode to mass flow, set point = flowrate_scc, ramping flowrate_sccm or zero to disable.

#### *async* set_gas(device_name, gas)

Set MFC to pure gas

#### *async* set_gas_mixture(device_name, gas_dict)

Set MFC to gas mixture defined in gas_dict {gasname: integer_pct}

#### *async* set_pressure(device_name, pressure_psia, ramp_psi_sec=0, \*args, \*\*kwargs)

Set control mode to pressure, set point = pressure_psi, ramping psi/sec or zero to disable.

#### shutdown()

#### *async* start_polling()

#### *async* stop_polling()

#### *async* tare_pressure(device_name=None)

Tare absolute pressure.

#### *async* tare_volume(device_name=None)

Tare volumetric flow. Ensure mfc is isolated.

#### *async* unlock_display(device_name=None)

Unlock the front display.

### *class* helao.drivers.mfc.alicat_driver.MfcConstPresExec(\*args, \*\*kwargs)

Bases: [`MfcExec`](#helao.drivers.mfc.alicat_driver.MfcExec)

#### \_\_init_\_(\*args, \*\*kwargs)

Initializes the Executor.

Args:
: active: The active action to be executed.
  poll_rate (float, optional): The rate at which to poll for updates. Defaults to 0.2.
  oneoff (bool, optional): Whether the executor is a one-off execution. Defaults to True.
  exec_id (str, optional): The unique identifier for the executor. If None, it will be generated. Defaults to None.
  concurrent (bool, optional): Whether multiple executors can run concurrently. Defaults to True.
  <br/>
  ```
  **
  ```
  <br/>
  kwargs: Additional keyword arguments.

Attributes:
: active: The active action to be executed.
  oneoff (bool): Whether the executor is a one-off execution.
  poll_rate (float): The rate at which to poll for updates.
  exec_id (str): The unique identifier for the executor.
  start_time (float): The start time of the execution.
  duration (float): The duration of the action.
  concurrent (bool): Whether multiple executors can run concurrently.

#### eval_pressure(pressure)

### *class* helao.drivers.mfc.alicat_driver.MfcExec(\*args, \*\*kwargs)

Bases: [`Executor`](helao.helpers.md#helao.helpers.executor.Executor)

#### \_\_init_\_(\*args, \*\*kwargs)

Initializes the Executor.

Args:
: active: The active action to be executed.
  poll_rate (float, optional): The rate at which to poll for updates. Defaults to 0.2.
  oneoff (bool, optional): Whether the executor is a one-off execution. Defaults to True.
  exec_id (str, optional): The unique identifier for the executor. If None, it will be generated. Defaults to None.
  concurrent (bool, optional): Whether multiple executors can run concurrently. Defaults to True.
  <br/>
  ```
  **
  ```
  <br/>
  kwargs: Additional keyword arguments.

Attributes:
: active: The active action to be executed.
  oneoff (bool): Whether the executor is a one-off execution.
  poll_rate (float): The rate at which to poll for updates.
  exec_id (str): The unique identifier for the executor.
  start_time (float): The start time of the execution.
  duration (float): The duration of the action.
  concurrent (bool): Whether multiple executors can run concurrently.

### *class* helao.drivers.mfc.alicat_driver.PfcExec(\*args, \*\*kwargs)

Bases: [`MfcExec`](#helao.drivers.mfc.alicat_driver.MfcExec)

## Module contents
