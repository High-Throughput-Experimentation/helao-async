# helao.drivers.spec package

## Subpackages

* [helao.drivers.spec.andor package](helao.drivers.spec.andor.md)
  * [Submodules](helao.drivers.spec.andor.md#submodules)
  * [helao.drivers.spec.andor.driver module](helao.drivers.spec.andor.md#helao-drivers-spec-andor-driver-module)
  * [helao.drivers.spec.andor.test_funcs module](helao.drivers.spec.andor.md#helao-drivers-spec-andor-test-funcs-module)
  * [Module contents](helao.drivers.spec.andor.md#module-helao.drivers.spec.andor)

## Submodules

## helao.drivers.spec.enum module

### *class* helao.drivers.spec.enum.ReferenceMode(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `str`, `Enum`

#### blank *= 'blank'*

#### builtin *= 'builtin'*

#### internal *= 'internal'*

### *class* helao.drivers.spec.enum.SpecTrigType(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `IntEnum`

#### external *= 12*

#### internal *= 11*

#### off *= 10*

### *class* helao.drivers.spec.enum.SpecType(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `str`, `Enum`

#### R *= 'R'*

#### T *= 'T'*

## helao.drivers.spec.spectral_products_driver module

### *class* helao.drivers.spec.spectral_products_driver.SM303(action_serv)

Bases: `object`

\_summary_

#### *async* IOloop()

This is trigger-acquire-read loop which always runs.

#### \_\_init_\_(action_serv)

#### acquire_spec_adv(int_time_ms, \*\*kwargs)

#### *async* acquire_spec_extrig(A)

Perform async acquisition based on external trigger.

Notes:
: SM303 has max ‘waiting time’ of 7ms, ADC time of 4ms, min USB tx
  time of 2ms in addition to the min integration time of 7ms.
  <br/>
  Trigger signal time must be at least 13ms.
  Galil IO appears to have 1ms toggle resolutionself.
  <br/>
  TODO: setup external trigger mode and integration time,
  SPEC server should switch over to usb context and listen for data,
  Galil IO or PSTAT should send SPEC server a finish signal

Return active dict.

#### close_spec_connection()

#### *async* continuous_read()

Async polling task.

‘start_margin’ is the number of seconds to extend the trigger acquisition window
to account for the time delay between SPEC and PSTAT actions

#### *async* estop(switch, \*args, \*\*kwargs)

same as stop, set or clear estop flag with switch parameter

#### read_data()

#### *async* set_IO_signalq(val)

* **Return type:**
  `None`

#### set_IO_signalq_nowait(val)

* **Return type:**
  `None`

#### set_extedge_mode(mode=TriggerType.risingedge)

#### set_integration_time(int_time=7.0)

#### set_trigger_mode(mode=SpecTrigType.off)

#### setup_sm303()

#### shutdown()

#### *async* stop(delay=0)

stops measurement, writes all data and returns from meas loop

#### unset_external_trigger()

## Module contents
