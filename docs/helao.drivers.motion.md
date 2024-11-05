# helao.drivers.motion package

## Submodules

## helao.drivers.motion.enum module

### *class* helao.drivers.motion.enum.MoveModes(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `str`, `Enum`

#### absolute *= 'absolute'*

#### homing *= 'homing'*

#### relative *= 'relative'*

### *class* helao.drivers.motion.enum.TransformationModes(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `str`, `Enum`

#### instrxy *= 'instrxy'*

#### motorxy *= 'motorxy'*

#### platexy *= 'platexy'*

## helao.drivers.motion.galil_motion_driver module

## helao.drivers.motion.kinesis_driver module

Thorlabs Kinesis motor driver class

Notes:
# list devices
devices = Thorlabs.list_kinesis_devices()

# connect to MLJ150/M
stage = Thorlabs.KinesisMotor(“49370234”, scale=(pos_scale, vel_scle, acc_scale))

# get current status (position, status list, motion parameters)
stage.get_full_status()

# move_by
# move_to
# home

# MLJ150/M – read ranges from kinesis application, switch between device and phys units
# position 0 - 61440000 :: 0 - 50 mm :: physical-to-internal = 1228800.0
# velocity 0 - 329853488 :: 0 - 5 mm/s :: physical-to-internal = 65970697.6
# accel 0 - 135182 :: 0 - 10 mm/s2 :: physical-to-internal = 13518.2

### *class* helao.drivers.motion.kinesis_driver.KinesisMotor(config={})

Bases: [`HelaoDriver`](helao.drivers.md#helao.drivers.helao_driver.HelaoDriver)

#### \_\_init_\_(config={})

Initializes the HelaoDriver instance.

Args:
: config (dict, optional): Configuration dictionary for the driver. Defaults to an empty dictionary.

Attributes:
: timestamp (datetime): The timestamp when the instance is created.
  config (dict): The configuration dictionary for the driver.

#### connect()

Open connection to resource.

* **Return type:**
  [`DriverResponse`](helao.drivers.md#helao.drivers.helao_driver.DriverResponse)

#### disconnect()

Release connection to resource.

* **Return type:**
  [`DriverResponse`](helao.drivers.md#helao.drivers.helao_driver.DriverResponse)

#### get_status()

Return current driver status.

* **Return type:**
  [`DriverResponse`](helao.drivers.md#helao.drivers.helao_driver.DriverResponse)

#### move(axis, move_mode, value)

* **Return type:**
  [`DriverResponse`](helao.drivers.md#helao.drivers.helao_driver.DriverResponse)

#### reset()

Reinitialize driver, force-close old connection if necessary.

* **Return type:**
  [`DriverResponse`](helao.drivers.md#helao.drivers.helao_driver.DriverResponse)

#### setup(axis, velocity=None, acceleration=None)

* **Return type:**
  [`DriverResponse`](helao.drivers.md#helao.drivers.helao_driver.DriverResponse)

#### stop(axis=None)

General stop method, abort all active methods e.g. motion, I/O, compute.

* **Return type:**
  [`DriverResponse`](helao.drivers.md#helao.drivers.helao_driver.DriverResponse)

### *class* helao.drivers.motion.kinesis_driver.KinesisPoller(driver, wait_time=0.05)

Bases: [`DriverPoller`](helao.drivers.md#helao.drivers.helao_driver.DriverPoller)

#### get_data()

Retrieves data from the driver.

This method is intended to be overridden by subclasses to provide
specific data retrieval functionality. By default, it logs a message
indicating that the method has not been implemented and returns an
empty DriverResponse object.

Returns:
: DriverResponse: An empty response object indicating no data.

### *class* helao.drivers.motion.kinesis_driver.MoveModes(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `str`, `Enum`

#### absolute *= 'absolute'*

#### relative *= 'relative'*

## Module contents
