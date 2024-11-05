# helao.drivers.temperature_control package

## Submodules

## helao.drivers.temperature_control.mecom_driver module

### *class* helao.drivers.temperature_control.mecom_driver.MeerstetterTEC(action_serv)

Bases: `object`

Controlling TEC devices via serial.

#### \_\_init_\_(action_serv)

#### disable()

#### enable()

#### get_data()

#### *async* poll_sensor_loop(frequency=1)

#### session()

#### set_temp(value)

Set object temperature of channel to desired value.
:type value: 
:param value: float
:param channel: int
:return:

#### shutdown()

### *class* helao.drivers.temperature_control.mecom_driver.TECMonExec(\*args, \*\*kwargs)

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

### *class* helao.drivers.temperature_control.mecom_driver.TECWaitExec(\*args, \*\*kwargs)

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

## Module contents
