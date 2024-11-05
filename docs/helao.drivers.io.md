# helao.drivers.io package

## Submodules

## helao.drivers.io.enum module

### *class* helao.drivers.io.enum.TriggerType(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `IntEnum`

#### blip *= 2*

#### fallingedge *= 0*

#### risingedge *= 1*

## helao.drivers.io.galil_io_driver module

## helao.drivers.io.nidaqmx_driver module

### *class* helao.drivers.io.nidaqmx_driver.cNIMAX(action_serv)

Bases: `object`

#### *async* Heatloop(duration_h, celltemp_min, celltemp_max, reservoir2_min, reservoir2_max)

attempt maintain temperatures for the mdatatemp task.

#### *async* IOloop()

only monitors the status and keeps track of time for the
multi cell iv task. This one will also handle estop, stop,
finishes the active object etc.

#### \_\_init_\_(action_serv)

#### create_IVtask()

configures a NImax task for multi cell IV measurements

#### create_monitortask()

configures and starts a NImax task for nonexperiment temp measurements

#### *async* estop(switch, \*args, \*\*kwargs)

same as estop, but also sets flag

#### *async* get_digital_in(di_port=None, di_name='', on=False, \*args, \*\*kwargs)

#### *async* monitorloop()

#### *async* read_T()

#### *async* run_cell_IV(A)

#### *async* set_IO_signalq(val)

* **Return type:**
  `None`

#### set_IO_signalq_nowait(val)

* **Return type:**
  `None`

#### *async* set_digital_out(do_port=None, do_name='', on=False, \*args, \*\*kwargs)

#### shutdown()

#### *async* stop()

stops measurement, writes all data and returns from meas loop

#### stop_heatloop()

stops instantaneous temp measurement

#### stop_monitor()

stops instantaneous temp measurement

#### streamIV_callback(task_handle, every_n_samples_event_type, number_of_samples, callback_data)

## Module contents
