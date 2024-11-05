# helao.drivers.pstat.gamry package

## Submodules

## helao.drivers.pstat.gamry.device module

### *class* helao.drivers.pstat.gamry.device.GamryPstat(device, ierange, set_sensemode, set_rangemode)

Bases: `object`

#### \_\_init_\_(device, ierange, set_sensemode, set_rangemode)

#### device *: `str`*

#### ierange *: `StrEnum`*

#### set_rangemode *: `bool`*

#### set_sensemode *: `bool`*

## helao.drivers.pstat.gamry.driver module

## helao.drivers.pstat.gamry.dtaq module

### *class* helao.drivers.pstat.gamry.dtaq.DtaqType(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `StrEnum`

#### ChronoAmp *= 'ChronoAmp'*

#### ChronoPot *= 'ChronoPot'*

### *class* helao.drivers.pstat.gamry.dtaq.GamryDtaq(name, dtaq_type=None, output_keys=<factory>, int_param_keys=<factory>, bool_param_keys=<factory>)

Bases: `object`

#### \_\_init_\_(name, dtaq_type=None, output_keys=<factory>, int_param_keys=<factory>, bool_param_keys=<factory>)

#### bool_param_keys *: `List`[`str`]*

#### dtaq_type *: `Optional`[[`DtaqType`](#helao.drivers.pstat.gamry.dtaq.DtaqType)]* *= None*

#### int_param_keys *: `List`[`str`]*

#### name *: `str`*

#### output_keys *: `List`[`str`]*

## helao.drivers.pstat.gamry.range module

### *class* helao.drivers.pstat.gamry.range.Gamry_IErange_IFC1010(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `StrEnum`

#### auto *= 'auto'*

#### mode10 *= '10mA'*

#### mode11 *= '100mA'*

#### mode12 *= '1A'*

#### mode4 *= '10nA'*

#### mode5 *= '100nA'*

#### mode6 *= '1uA'*

#### mode7 *= '10uA'*

#### mode8 *= '100uA'*

#### mode9 *= '1mA'*

### *class* helao.drivers.pstat.gamry.range.Gamry_IErange_PCI4G300(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `StrEnum`

#### auto *= 'auto'*

#### mode10 *= '30mA'*

#### mode11 *= '300mA'*

#### mode3 *= '3nA'*

#### mode4 *= '30nA'*

#### mode5 *= '300nA'*

#### mode6 *= '3uA'*

#### mode7 *= '30uA'*

#### mode8 *= '300uA'*

#### mode9 *= '3mA'*

### *class* helao.drivers.pstat.gamry.range.Gamry_IErange_PCI4G750(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `StrEnum`

#### auto *= 'auto'*

#### mode10 *= '75mA'*

#### mode11 *= '750mA'*

#### mode3 *= '7.5nA'*

#### mode4 *= '75nA'*

#### mode5 *= '750nA'*

#### mode6 *= '7.5uA'*

#### mode7 *= '75uA'*

#### mode8 *= '750uA'*

#### mode9 *= '7.5mA'*

### *class* helao.drivers.pstat.gamry.range.Gamry_IErange_REF600(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `StrEnum`

#### auto *= 'auto'*

#### mode1 *= '60pA'*

#### mode10 *= '60mA'*

#### mode11 *= '600mA'*

#### mode2 *= '600pA'*

#### mode3 *= '6nA'*

#### mode4 *= '60nA'*

#### mode5 *= '600nA'*

#### mode6 *= '6uA'*

#### mode7 *= '60uA'*

#### mode8 *= '600uA'*

#### mode9 *= '6mA'*

### *class* helao.drivers.pstat.gamry.range.Gamry_IErange_dflt(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `StrEnum`

#### auto *= 'auto'*

#### mode0 *= 'mode0'*

#### mode1 *= 'mode1'*

#### mode10 *= 'mode10'*

#### mode11 *= 'mode11'*

#### mode12 *= 'mode12'*

#### mode13 *= 'mode13'*

#### mode14 *= 'mode14'*

#### mode15 *= 'mode15'*

#### mode2 *= 'mode2'*

#### mode3 *= 'mode3'*

#### mode4 *= 'mode4'*

#### mode5 *= 'mode5'*

#### mode6 *= 'mode6'*

#### mode7 *= 'mode7'*

#### mode8 *= 'mode8'*

#### mode9 *= 'mode9'*

### helao.drivers.pstat.gamry.range.get_range(requested_range, range_enum)

### helao.drivers.pstat.gamry.range.split_val_unit(val_string)

* **Return type:**
  `tuple`[`float`, `str`]

### helao.drivers.pstat.gamry.range.to_amps(number, unit)

* **Return type:**
  `Optional`[`float`]

## helao.drivers.pstat.gamry.signal module

Dataclass and instances for Gamry potentiostat signals.

Parameter keys are ordered according to GamryCOM.GamrySignal\* Init() args, and names are
modified as little as possible with the exception of ScanRate -> AcqInterval_\_s.

### *class* helao.drivers.pstat.gamry.signal.ControlMode(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `StrEnum`

#### GstatMode *= 'GstatMode'*

#### PstatMode *= 'PstatMode'*

### *class* helao.drivers.pstat.gamry.signal.GamrySignal(name, mode, param_keys=<factory>, init_keys=<factory>, map_keys=<factory>)

Bases: `object`

#### \_\_init_\_(name, mode, param_keys=<factory>, init_keys=<factory>, map_keys=<factory>)

#### init_keys *: `List`[`str`]*

#### map_keys *: `Dict`[`str`, `Union`[`int`, `float`, `str`]]*

#### mode *: [`ControlMode`](#helao.drivers.pstat.gamry.signal.ControlMode)*

#### name *: `str`*

#### param_keys *: `List`[`str`]*

## helao.drivers.pstat.gamry.sink module

### *class* helao.drivers.pstat.gamry.sink.DummySink(dtaq=None, status='idle', acquired_points=<factory>, buffer_size=0)

Bases: `object`

Dummy class for when the Gamry is not used.

#### \_\_init_\_(dtaq=None, status='idle', acquired_points=<factory>, buffer_size=0)

#### acquired_points *: `list`*

#### buffer_size *: `int`* *= 0*

#### dtaq *: `object`* *= None*

#### status *: `str`* *= 'idle'*

### *class* helao.drivers.pstat.gamry.sink.GamryDtaqSink(dtaq)

Bases: `object`

Event sink for reading data from Gamry device.

#### \_\_init_\_(dtaq)

#### cook()

## helao.drivers.pstat.gamry.technique module

Dataclass and instances for Gamry potentiostat techniques.

### *class* helao.drivers.pstat.gamry.technique.GamryTechnique(name, on_method, dtaq, signal, set_decimation=None, set_vchrangemode=None, set_ierangemode=None, vchrange_keys=None, ierange_keys=None)

Bases: `object`

#### \_\_init_\_(name, on_method, dtaq, signal, set_decimation=None, set_vchrangemode=None, set_ierangemode=None, vchrange_keys=None, ierange_keys=None)

#### dtaq *: [`GamryDtaq`](#helao.drivers.pstat.gamry.dtaq.GamryDtaq)*

#### ierange_keys *: `Optional`[`List`[`str`]]* *= None*

#### name *: `str`*

#### on_method *: [`OnMethod`](#helao.drivers.pstat.gamry.technique.OnMethod)*

#### set_decimation *: `Optional`[`bool`]* *= None*

#### set_ierangemode *: `Optional`[`bool`]* *= None*

#### set_vchrangemode *: `Optional`[`bool`]* *= None*

#### signal *: [`GamrySignal`](#helao.drivers.pstat.gamry.signal.GamrySignal)*

#### vchrange_keys *: `Optional`[`List`[`str`]]* *= None*

### *class* helao.drivers.pstat.gamry.technique.OnMethod(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `StrEnum`

#### CellMon *= 'CellMon'*

#### CellOn *= 'CellOn'*

## Module contents
