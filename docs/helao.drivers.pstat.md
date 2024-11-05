# helao.drivers.pstat package

## Subpackages

* [helao.drivers.pstat.biologic package](helao.drivers.pstat.biologic.md)
  * [Submodules](helao.drivers.pstat.biologic.md#submodules)
  * [helao.drivers.pstat.biologic.driver module](helao.drivers.pstat.biologic.md#helao-drivers-pstat-biologic-driver-module)
  * [helao.drivers.pstat.biologic.technique module](helao.drivers.pstat.biologic.md#helao-drivers-pstat-biologic-technique-module)
  * [Module contents](helao.drivers.pstat.biologic.md#module-helao.drivers.pstat.biologic)
* [helao.drivers.pstat.gamry package](helao.drivers.pstat.gamry.md)
  * [Submodules](helao.drivers.pstat.gamry.md#submodules)
  * [helao.drivers.pstat.gamry.device module](helao.drivers.pstat.gamry.md#module-helao.drivers.pstat.gamry.device)
    * [`GamryPstat`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.device.GamryPstat)
      * [`GamryPstat.__init__()`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.device.GamryPstat.__init__)
      * [`GamryPstat.device`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.device.GamryPstat.device)
      * [`GamryPstat.ierange`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.device.GamryPstat.ierange)
      * [`GamryPstat.set_rangemode`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.device.GamryPstat.set_rangemode)
      * [`GamryPstat.set_sensemode`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.device.GamryPstat.set_sensemode)
  * [helao.drivers.pstat.gamry.driver module](helao.drivers.pstat.gamry.md#helao-drivers-pstat-gamry-driver-module)
  * [helao.drivers.pstat.gamry.dtaq module](helao.drivers.pstat.gamry.md#module-helao.drivers.pstat.gamry.dtaq)
    * [`DtaqType`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.dtaq.DtaqType)
      * [`DtaqType.ChronoAmp`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.dtaq.DtaqType.ChronoAmp)
      * [`DtaqType.ChronoPot`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.dtaq.DtaqType.ChronoPot)
    * [`GamryDtaq`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.dtaq.GamryDtaq)
      * [`GamryDtaq.__init__()`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.dtaq.GamryDtaq.__init__)
      * [`GamryDtaq.bool_param_keys`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.dtaq.GamryDtaq.bool_param_keys)
      * [`GamryDtaq.dtaq_type`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.dtaq.GamryDtaq.dtaq_type)
      * [`GamryDtaq.int_param_keys`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.dtaq.GamryDtaq.int_param_keys)
      * [`GamryDtaq.name`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.dtaq.GamryDtaq.name)
      * [`GamryDtaq.output_keys`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.dtaq.GamryDtaq.output_keys)
  * [helao.drivers.pstat.gamry.range module](helao.drivers.pstat.gamry.md#module-helao.drivers.pstat.gamry.range)
    * [`Gamry_IErange_IFC1010`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_IFC1010)
      * [`Gamry_IErange_IFC1010.auto`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_IFC1010.auto)
      * [`Gamry_IErange_IFC1010.mode10`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_IFC1010.mode10)
      * [`Gamry_IErange_IFC1010.mode11`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_IFC1010.mode11)
      * [`Gamry_IErange_IFC1010.mode12`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_IFC1010.mode12)
      * [`Gamry_IErange_IFC1010.mode4`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_IFC1010.mode4)
      * [`Gamry_IErange_IFC1010.mode5`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_IFC1010.mode5)
      * [`Gamry_IErange_IFC1010.mode6`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_IFC1010.mode6)
      * [`Gamry_IErange_IFC1010.mode7`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_IFC1010.mode7)
      * [`Gamry_IErange_IFC1010.mode8`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_IFC1010.mode8)
      * [`Gamry_IErange_IFC1010.mode9`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_IFC1010.mode9)
    * [`Gamry_IErange_PCI4G300`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_PCI4G300)
      * [`Gamry_IErange_PCI4G300.auto`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_PCI4G300.auto)
      * [`Gamry_IErange_PCI4G300.mode10`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_PCI4G300.mode10)
      * [`Gamry_IErange_PCI4G300.mode11`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_PCI4G300.mode11)
      * [`Gamry_IErange_PCI4G300.mode3`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_PCI4G300.mode3)
      * [`Gamry_IErange_PCI4G300.mode4`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_PCI4G300.mode4)
      * [`Gamry_IErange_PCI4G300.mode5`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_PCI4G300.mode5)
      * [`Gamry_IErange_PCI4G300.mode6`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_PCI4G300.mode6)
      * [`Gamry_IErange_PCI4G300.mode7`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_PCI4G300.mode7)
      * [`Gamry_IErange_PCI4G300.mode8`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_PCI4G300.mode8)
      * [`Gamry_IErange_PCI4G300.mode9`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_PCI4G300.mode9)
    * [`Gamry_IErange_PCI4G750`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_PCI4G750)
      * [`Gamry_IErange_PCI4G750.auto`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_PCI4G750.auto)
      * [`Gamry_IErange_PCI4G750.mode10`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_PCI4G750.mode10)
      * [`Gamry_IErange_PCI4G750.mode11`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_PCI4G750.mode11)
      * [`Gamry_IErange_PCI4G750.mode3`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_PCI4G750.mode3)
      * [`Gamry_IErange_PCI4G750.mode4`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_PCI4G750.mode4)
      * [`Gamry_IErange_PCI4G750.mode5`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_PCI4G750.mode5)
      * [`Gamry_IErange_PCI4G750.mode6`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_PCI4G750.mode6)
      * [`Gamry_IErange_PCI4G750.mode7`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_PCI4G750.mode7)
      * [`Gamry_IErange_PCI4G750.mode8`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_PCI4G750.mode8)
      * [`Gamry_IErange_PCI4G750.mode9`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_PCI4G750.mode9)
    * [`Gamry_IErange_REF600`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_REF600)
      * [`Gamry_IErange_REF600.auto`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_REF600.auto)
      * [`Gamry_IErange_REF600.mode1`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_REF600.mode1)
      * [`Gamry_IErange_REF600.mode10`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_REF600.mode10)
      * [`Gamry_IErange_REF600.mode11`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_REF600.mode11)
      * [`Gamry_IErange_REF600.mode2`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_REF600.mode2)
      * [`Gamry_IErange_REF600.mode3`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_REF600.mode3)
      * [`Gamry_IErange_REF600.mode4`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_REF600.mode4)
      * [`Gamry_IErange_REF600.mode5`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_REF600.mode5)
      * [`Gamry_IErange_REF600.mode6`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_REF600.mode6)
      * [`Gamry_IErange_REF600.mode7`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_REF600.mode7)
      * [`Gamry_IErange_REF600.mode8`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_REF600.mode8)
      * [`Gamry_IErange_REF600.mode9`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_REF600.mode9)
    * [`Gamry_IErange_dflt`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_dflt)
      * [`Gamry_IErange_dflt.auto`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_dflt.auto)
      * [`Gamry_IErange_dflt.mode0`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_dflt.mode0)
      * [`Gamry_IErange_dflt.mode1`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_dflt.mode1)
      * [`Gamry_IErange_dflt.mode10`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_dflt.mode10)
      * [`Gamry_IErange_dflt.mode11`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_dflt.mode11)
      * [`Gamry_IErange_dflt.mode12`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_dflt.mode12)
      * [`Gamry_IErange_dflt.mode13`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_dflt.mode13)
      * [`Gamry_IErange_dflt.mode14`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_dflt.mode14)
      * [`Gamry_IErange_dflt.mode15`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_dflt.mode15)
      * [`Gamry_IErange_dflt.mode2`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_dflt.mode2)
      * [`Gamry_IErange_dflt.mode3`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_dflt.mode3)
      * [`Gamry_IErange_dflt.mode4`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_dflt.mode4)
      * [`Gamry_IErange_dflt.mode5`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_dflt.mode5)
      * [`Gamry_IErange_dflt.mode6`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_dflt.mode6)
      * [`Gamry_IErange_dflt.mode7`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_dflt.mode7)
      * [`Gamry_IErange_dflt.mode8`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_dflt.mode8)
      * [`Gamry_IErange_dflt.mode9`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.Gamry_IErange_dflt.mode9)
    * [`get_range()`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.get_range)
    * [`split_val_unit()`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.split_val_unit)
    * [`to_amps()`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.range.to_amps)
  * [helao.drivers.pstat.gamry.signal module](helao.drivers.pstat.gamry.md#module-helao.drivers.pstat.gamry.signal)
    * [`ControlMode`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.signal.ControlMode)
      * [`ControlMode.GstatMode`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.signal.ControlMode.GstatMode)
      * [`ControlMode.PstatMode`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.signal.ControlMode.PstatMode)
    * [`GamrySignal`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.signal.GamrySignal)
      * [`GamrySignal.__init__()`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.signal.GamrySignal.__init__)
      * [`GamrySignal.init_keys`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.signal.GamrySignal.init_keys)
      * [`GamrySignal.map_keys`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.signal.GamrySignal.map_keys)
      * [`GamrySignal.mode`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.signal.GamrySignal.mode)
      * [`GamrySignal.name`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.signal.GamrySignal.name)
      * [`GamrySignal.param_keys`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.signal.GamrySignal.param_keys)
  * [helao.drivers.pstat.gamry.sink module](helao.drivers.pstat.gamry.md#module-helao.drivers.pstat.gamry.sink)
    * [`DummySink`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.sink.DummySink)
      * [`DummySink.__init__()`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.sink.DummySink.__init__)
      * [`DummySink.acquired_points`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.sink.DummySink.acquired_points)
      * [`DummySink.buffer_size`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.sink.DummySink.buffer_size)
      * [`DummySink.dtaq`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.sink.DummySink.dtaq)
      * [`DummySink.status`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.sink.DummySink.status)
    * [`GamryDtaqSink`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.sink.GamryDtaqSink)
      * [`GamryDtaqSink.__init__()`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.sink.GamryDtaqSink.__init__)
      * [`GamryDtaqSink.cook()`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.sink.GamryDtaqSink.cook)
  * [helao.drivers.pstat.gamry.technique module](helao.drivers.pstat.gamry.md#module-helao.drivers.pstat.gamry.technique)
    * [`GamryTechnique`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.technique.GamryTechnique)
      * [`GamryTechnique.__init__()`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.technique.GamryTechnique.__init__)
      * [`GamryTechnique.dtaq`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.technique.GamryTechnique.dtaq)
      * [`GamryTechnique.ierange_keys`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.technique.GamryTechnique.ierange_keys)
      * [`GamryTechnique.name`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.technique.GamryTechnique.name)
      * [`GamryTechnique.on_method`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.technique.GamryTechnique.on_method)
      * [`GamryTechnique.set_decimation`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.technique.GamryTechnique.set_decimation)
      * [`GamryTechnique.set_ierangemode`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.technique.GamryTechnique.set_ierangemode)
      * [`GamryTechnique.set_vchrangemode`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.technique.GamryTechnique.set_vchrangemode)
      * [`GamryTechnique.signal`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.technique.GamryTechnique.signal)
      * [`GamryTechnique.vchrange_keys`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.technique.GamryTechnique.vchrange_keys)
    * [`OnMethod`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.technique.OnMethod)
      * [`OnMethod.CellMon`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.technique.OnMethod.CellMon)
      * [`OnMethod.CellOn`](helao.drivers.pstat.gamry.md#helao.drivers.pstat.gamry.technique.OnMethod.CellOn)
  * [Module contents](helao.drivers.pstat.gamry.md#module-helao.drivers.pstat.gamry)

## Submodules

## helao.drivers.pstat.cpsim_driver module

## helao.drivers.pstat.enum module

### *class* helao.drivers.pstat.enum.Gamry_IErange_IFC1010(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `str`, `Enum`

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

### *class* helao.drivers.pstat.enum.Gamry_IErange_PCI4G300(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `str`, `Enum`

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

### *class* helao.drivers.pstat.enum.Gamry_IErange_PCI4G750(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `str`, `Enum`

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

### *class* helao.drivers.pstat.enum.Gamry_IErange_REF600(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `str`, `Enum`

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

### *class* helao.drivers.pstat.enum.Gamry_IErange_dflt(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `str`, `Enum`

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

### *class* helao.drivers.pstat.enum.Gamry_modes(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `str`, `Enum`

#### CA *= 'CA'*

#### CP *= 'CP'*

#### CV *= 'CV'*

#### EIS *= 'EIS'*

#### LSV *= 'LSV'*

#### OCV *= 'OCV'*

#### RCA *= 'RCA'*

## helao.drivers.pstat.gamry_driver module

## Module contents
