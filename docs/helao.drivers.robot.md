# helao.drivers.robot package

## Submodules

## helao.drivers.robot.enum module

### *class* helao.drivers.robot.enum.CAMS(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `Enum`

#### archive *= \_cam(name='archive', file_name='', file_path=None, sample_out_type='liquid', ttl_start=False, ttl_continue=False, ttl_done=False, source='custom', dest='next_empty_vial')*

#### deepclean *= \_cam(name='deepclean', file_name='', file_path=None, sample_out_type=None, ttl_start=False, ttl_continue=False, ttl_done=False, source=None, dest=None)*

#### injection_custom_GC_gas_start *= \_cam(name='injection_custom_GC_gas_start', file_name='', file_path=None, sample_out_type='gas', ttl_start=False, ttl_continue=False, ttl_done=False, source='custom', dest='custom')*

#### injection_custom_GC_gas_wait *= \_cam(name='injection_custom_GC_gas_wait', file_name='', file_path=None, sample_out_type='gas', ttl_start=False, ttl_continue=False, ttl_done=False, source='custom', dest='custom')*

#### injection_custom_GC_liquid_start *= \_cam(name='injection_custom_GC_liquid_start', file_name='', file_path=None, sample_out_type='liquid', ttl_start=False, ttl_continue=False, ttl_done=False, source='custom', dest='custom')*

#### injection_custom_GC_liquid_wait *= \_cam(name='injection_custom_GC_liquid_wait', file_name='', file_path=None, sample_out_type='liquid', ttl_start=False, ttl_continue=False, ttl_done=False, source='custom', dest='custom')*

#### injection_custom_HPLC *= \_cam(name='injection_custom_HPLC', file_name='', file_path=None, sample_out_type='liquid', ttl_start=False, ttl_continue=False, ttl_done=False, source='custom', dest='custom')*

#### injection_tray_GC_gas_start *= \_cam(name='injection_tray_GC_gas_start', file_name='', file_path=None, sample_out_type='gas', ttl_start=False, ttl_continue=False, ttl_done=False, source='tray', dest='custom')*

#### injection_tray_GC_gas_wait *= \_cam(name='injection_tray_GC_gas_wait', file_name='', file_path=None, sample_out_type='gas', ttl_start=False, ttl_continue=False, ttl_done=False, source='tray', dest='custom')*

#### injection_tray_GC_liquid_start *= \_cam(name='injection_tray_GC_liquid_start', file_name='', file_path=None, sample_out_type='liquid', ttl_start=False, ttl_continue=False, ttl_done=False, source='tray', dest='custom')*

#### injection_tray_GC_liquid_wait *= \_cam(name='injection_tray_GC_liquid_wait', file_name='', file_path=None, sample_out_type='liquid', ttl_start=False, ttl_continue=False, ttl_done=False, source='tray', dest='custom')*

#### injection_tray_HPLC *= \_cam(name='injection_tray_HPLC', file_name='', file_path=None, sample_out_type='liquid', ttl_start=False, ttl_continue=False, ttl_done=False, source='tray', dest='custom')*

#### none *= \_cam(name='', file_name='', file_path=None, sample_out_type=None, ttl_start=False, ttl_continue=False, ttl_done=False, source=None, dest=None)*

#### transfer_custom_custom *= \_cam(name='transfer_tray_custom', file_name='', file_path=None, sample_out_type='liquid', ttl_start=False, ttl_continue=False, ttl_done=False, source='custom', dest='custom')*

#### transfer_custom_tray *= \_cam(name='transfer_custom_tray', file_name='', file_path=None, sample_out_type='liquid', ttl_start=False, ttl_continue=False, ttl_done=False, source='custom', dest='tray')*

#### transfer_tray_custom *= \_cam(name='transfer_tray_custom', file_name='', file_path=None, sample_out_type='liquid', ttl_start=False, ttl_continue=False, ttl_done=False, source='tray', dest='custom')*

#### transfer_tray_tray *= \_cam(name='transfer_tray_tray', file_name='', file_path=None, sample_out_type='liquid', ttl_start=False, ttl_continue=False, ttl_done=False, source='tray', dest='tray')*

### *class* helao.drivers.robot.enum.GCsampletype(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `str`, `Enum`

#### gas *= 'gas'*

#### liquid *= 'liquid'*

#### none *= 'none'*

### *class* helao.drivers.robot.enum.PALtools(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `str`, `Enum`

#### HS1 *= 'HS 1'*

#### HS2 *= 'HS 2'*

#### LS1 *= 'LS 1'*

#### LS2 *= 'LS 2'*

#### LS3 *= 'LS 3'*

#### LS4 *= 'LS 4'*

#### LS5 *= 'LS 5'*

### *class* helao.drivers.robot.enum.Spacingmethod(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `str`, `Enum`

#### custom *= 'custom'*

#### geometric *= 'gemoetric'*

#### linear *= 'linear'*

## helao.drivers.robot.pal_driver module

### *class* helao.drivers.robot.pal_driver.GCsampletype(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `str`, `Enum`

#### gas *= 'gas'*

#### liquid *= 'liquid'*

#### none *= 'none'*

### *class* helao.drivers.robot.pal_driver.PAL(action_serv)

Bases: `object`

#### \_\_init_\_(action_serv)

#### check_tool(req_tool=None)

#### *async* estop(switch, \*args, \*\*kwargs)

same as estop, but also sets flag

#### *async* kill_PAL()

kills PAL program if its still open

* **Return type:**
  `ErrorCodes`

#### *async* kill_PAL_cygwin()

* **Return type:**
  `bool`

#### *async* kill_PAL_local()

* **Return type:**
  `bool`

#### *async* method_ANEC_GC(A)

* **Return type:**
  `dict`

#### *async* method_ANEC_aliquot(A)

* **Return type:**
  `dict`

#### *async* method_arbitrary(A)

* **Return type:**
  `dict`

#### *async* method_archive(A)

* **Return type:**
  `dict`

#### *async* method_deepclean(A)

* **Return type:**
  `dict`

#### *async* method_injection_custom_GC(A)

* **Return type:**
  `dict`

#### *async* method_injection_custom_HPLC(A)

* **Return type:**
  `dict`

#### *async* method_injection_tray_GC(A)

* **Return type:**
  `dict`

#### *async* method_injection_tray_HPLC(A)

* **Return type:**
  `dict`

#### *async* method_transfer_custom_custom(A)

* **Return type:**
  `dict`

#### *async* method_transfer_custom_tray(A)

* **Return type:**
  `dict`

#### *async* method_transfer_tray_custom(A)

* **Return type:**
  `dict`

#### *async* method_transfer_tray_tray(A)

* **Return type:**
  `dict`

#### *async* set_IO_signalq(val)

* **Return type:**
  `None`

#### set_IO_signalq_nowait(val)

* **Return type:**
  `None`

#### shutdown()

#### *async* stop()

stops measurement, writes all data and returns from meas loop

### *class* helao.drivers.robot.pal_driver.PALposition(\*\*data)

Bases: `BaseModel`, `HelaoDict`

#### error *: `Optional`[`ErrorCodes`]*

#### model_computed_fields *: ClassVar[Dict[str, ComputedFieldInfo]]* *= {}*

A dictionary of computed field names and their corresponding ComputedFieldInfo objects.

#### model_config *: ClassVar[ConfigDict]* *= {}*

Configuration for the model, should be a dictionary conforming to [ConfigDict][pydantic.config.ConfigDict].

#### model_fields *: ClassVar[Dict[str, FieldInfo]]* *= {'error': FieldInfo(annotation=Union[ErrorCodes, NoneType], required=False, default=<ErrorCodes.none: 'none'>), 'position': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'samples_final': FieldInfo(annotation=List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]], required=False, default=[]), 'samples_initial': FieldInfo(annotation=List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]], required=False, default=[]), 'slot': FieldInfo(annotation=Union[int, NoneType], required=False, default=None), 'tray': FieldInfo(annotation=Union[int, NoneType], required=False, default=None), 'vial': FieldInfo(annotation=Union[int, NoneType], required=False, default=None)}*

Metadata about the fields defined on the model,
mapping of field names to [FieldInfo][pydantic.fields.FieldInfo] objects.

This replaces Model._\_fields_\_ from Pydantic V1.

#### position *: `Optional`[`str`]*

#### samples_final *: `List`[`Union`[`AssemblySample`, `LiquidSample`, `GasSample`, `SolidSample`, `NoneSample`]]*

#### samples_initial *: `List`[`Union`[`AssemblySample`, `LiquidSample`, `GasSample`, `SolidSample`, `NoneSample`]]*

#### slot *: `Optional`[`int`]*

#### tray *: `Optional`[`int`]*

#### vial *: `Optional`[`int`]*

### *class* helao.drivers.robot.pal_driver.PALtools(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `str`, `Enum`

#### HS1 *= 'HS 1'*

#### HS2 *= 'HS 2'*

#### LS1 *= 'LS 1'*

#### LS2 *= 'LS 2'*

#### LS3 *= 'LS 3'*

#### LS4 *= 'LS 4'*

#### LS5 *= 'LS 5'*

### *class* helao.drivers.robot.pal_driver.Spacingmethod(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `str`, `Enum`

#### custom *= 'custom'*

#### geometric *= 'gemoetric'*

#### linear *= 'linear'*

## Module contents
