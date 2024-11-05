# helao.drivers.sensor package

## Submodules

## helao.drivers.sensor.axiscam_driver module

A device class for the Axis M1103 webcam.

### *class* helao.drivers.sensor.axiscam_driver.AxisCam(action_serv)

Bases: `object`

#### \_\_init_\_(action_serv)

#### acquire_image()

Save image stream.

#### shutdown()

### *class* helao.drivers.sensor.axiscam_driver.AxisCamExec(\*args, \*\*kwargs)

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

#### *async* write_image(imgbytes, epoch)

Write image to action output directory.

## helao.drivers.sensor.cm0134_driver module

## helao.drivers.sensor.sprintir_driver module

A device class for the SprintIR-6S CO2 sensor.

## Module contents
