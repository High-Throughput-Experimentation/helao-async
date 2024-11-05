# helao.drivers.data.analyses package

## Submodules

## helao.drivers.data.analyses.base_analysis module

### *class* helao.drivers.data.analyses.base_analysis.BaseAnalysis

Bases: `object`

BaseAnalysis class for handling analysis data and exporting results.
Attributes:

> analysis_name (str): Name of the analysis.
> analysis_timestamp (datetime): Timestamp of the analysis.
> analysis_uuid (UUID): Unique identifier for the analysis.
> analysis_params (dict): Parameters for the analysis.
> process_uuid (UUID): Unique identifier for the process.
> process_timestamp (datetime): Timestamp of the process.
> process_name (str): Name of the process.
> run_type (str): Type of the run.
> technique_name (str): Name of the technique used.
> inputs (AnalysisInput): Input data for the analysis.
> outputs (BaseModel): Output data from the analysis.
> analysis_codehash (str): Hash of the analysis code.

Methods:
: gen_uuid(global_sample_label: Optional[str] = None) -> UUID:
  : Generates a unique identifier for the analysis based on input data models and parameters.
  <br/>
  export_analysis(bucket: str, region: str, dummy: bool = True, global_sample_label: Optional[str] = None) -> Tuple[dict, dict]:
  : Exports the analysis results to a specified S3 bucket and returns the analysis model and outputs.

#### analysis_codehash *: `str`*

#### analysis_name *: `str`*

#### analysis_params *: `dict`*

#### analysis_timestamp *: `datetime`*

#### analysis_uuid *: `UUID`*

#### export_analysis(bucket, region, dummy=True, global_sample_label=None)

Export the analysis results to a structured format.

Args:
: bucket (str): The S3 bucket where the analysis output will be stored.
  region (str): The AWS region where the S3 bucket is located.
  dummy (bool, optional): A flag indicating whether this is a dummy run. Defaults to True.
  global_sample_label (Optional[str], optional): A label for the global sample. Defaults to None.

Returns:
: Tuple[Dict, Dict]: A tuple containing the cleaned analysis model dictionary and the outputs model dump.

Raises:
: ValueError: If the analysis does not contain any outputs.

Notes:
: - The function retrieves input data models based on the global sample label.
  - It categorizes the outputs into scalar and array outputs.
  - It constructs output data models for each category and appends them to the output data models list.
  - If no output data models are found, a message is printed indicating the absence of outputs.
  - An AnalysisModel instance is created with the relevant details and returned as a cleaned dictionary along with the outputs model dump.

#### gen_uuid(global_sample_label=None)

Generates a UUID for the analysis based on various attributes.

Parameters:
global_sample_label (Optional[str]): A label for the global sample. If not provided,

> it will be derived from the input data models.

Returns:
UUID: A unique identifier generated from the hash representation of the analysis attributes.

The UUID is generated using a hash representation that includes:
- analysis_name: The name of the analysis.
- analysis_params: The parameters of the analysis.
- process_uuid: The UUID of the process.
- global_sample_label: The global sample label.
- analysis_codehash: The hash of the analysis code.

#### inputs *: `AnalysisInput`*

#### outputs *: `BaseModel`*

#### process_name *: `str`*

#### process_timestamp *: `datetime`*

#### process_uuid *: `UUID`*

#### run_type *: `str`*

#### technique_name *: `str`*

## helao.drivers.data.analyses.echeuvis_stability module

### *class* helao.drivers.data.analyses.echeuvis_stability.EcheUvisAnalysis(process_uuid, query_df, analysis_params)

Bases: [`BaseAnalysis`](#helao.drivers.data.analyses.base_analysis.BaseAnalysis)

ECHEUVIS Optical Stability Analysis for GCLD demonstration.

#### \_\_init_\_(process_uuid, query_df, analysis_params)

#### analysis_codehash *: `str`*

#### analysis_name *: `str`*

#### analysis_params *: `dict`*

#### analysis_timestamp *: `datetime`*

#### analysis_uuid *: `UUID`*

#### ca_potential_vrhe *: `float`*

#### calc_output()

Calculate stability FOMs and intermediate vectors.

#### inputs *: `AnalysisInput`*

#### outputs *: [`EcheUvisOutputs`](#helao.drivers.data.analyses.echeuvis_stability.EcheUvisOutputs)*

#### plate_id *: `int`*

#### process_name *: `str`*

#### process_timestamp *: `datetime`*

#### process_uuid *: `UUID`*

#### run_type *: `str`*

#### sample_no *: `int`*

#### technique_name *: `str`*

### *class* helao.drivers.data.analyses.echeuvis_stability.EcheUvisInputs(insitu_process_uuid, plate_id, sample_no, query_df)

Bases: `AnalysisInput`

#### \_\_init_\_(insitu_process_uuid, plate_id, sample_no, query_df)

#### baseline *: [`HelaoProcess`](helao.drivers.data.loaders.md#helao.drivers.data.loaders.pgs3.HelaoProcess)*

#### *property* baseline_ocv

#### baseline_ocv_act *: [`HelaoAction`](helao.drivers.data.loaders.md#helao.drivers.data.loaders.pgs3.HelaoAction)*

#### *property* baseline_spec

#### baseline_spec_act *: [`HelaoAction`](helao.drivers.data.loaders.md#helao.drivers.data.loaders.pgs3.HelaoAction)*

#### get_datamodels(global_sample_label, \*args, \*\*kwargs)

* **Return type:**
  `List`[`AnalysisDataModel`]

#### insitu *: [`HelaoProcess`](helao.drivers.data.loaders.md#helao.drivers.data.loaders.pgs3.HelaoProcess)*

#### *property* insitu_ca

#### insitu_ca_act *: [`HelaoAction`](helao.drivers.data.loaders.md#helao.drivers.data.loaders.pgs3.HelaoAction)*

#### *property* insitu_spec

#### insitu_spec_act *: [`HelaoAction`](helao.drivers.data.loaders.md#helao.drivers.data.loaders.pgs3.HelaoAction)*

#### presitu *: [`HelaoProcess`](helao.drivers.data.loaders.md#helao.drivers.data.loaders.pgs3.HelaoProcess)*

#### *property* presitu_ocv

#### presitu_ocv_act *: [`HelaoAction`](helao.drivers.data.loaders.md#helao.drivers.data.loaders.pgs3.HelaoAction)*

#### *property* presitu_spec

#### presitu_spec_act *: [`HelaoAction`](helao.drivers.data.loaders.md#helao.drivers.data.loaders.pgs3.HelaoAction)*

#### process_params *: `dict`*

### *class* helao.drivers.data.analyses.echeuvis_stability.EcheUvisOutputs(\*\*data)

Bases: `BaseModel`

#### agg_baseline *: `list`*

#### agg_insitu *: `list`*

#### agg_method *: `str`*

#### agg_presitu *: `list`*

#### baseline_max_rescaled *: `bool`*

#### baseline_min_rescaled *: `bool`*

#### bin_baseline *: `list`*

#### bin_insitu *: `list`*

#### bin_presitu *: `list`*

#### bin_wavelength *: `list`*

#### insitu_max_rescaled *: `bool`*

#### insitu_min_rescaled *: `bool`*

#### lower_wl_idx *: `int`*

#### mean_abs_omT_diff *: `float`*

#### mean_abs_omT_ratio *: `float`*

#### mean_ref_dark *: `list`*

#### mean_ref_light *: `list`*

#### model_computed_fields *: ClassVar[Dict[str, ComputedFieldInfo]]* *= {}*

A dictionary of computed field names and their corresponding ComputedFieldInfo objects.

#### model_config *: ClassVar[ConfigDict]* *= {}*

Configuration for the model, should be a dictionary conforming to [ConfigDict][pydantic.config.ConfigDict].

#### model_fields *: ClassVar[Dict[str, FieldInfo]]* *= {'agg_baseline': FieldInfo(annotation=list, required=True), 'agg_insitu': FieldInfo(annotation=list, required=True), 'agg_method': FieldInfo(annotation=str, required=True), 'agg_presitu': FieldInfo(annotation=list, required=True), 'baseline_max_rescaled': FieldInfo(annotation=bool, required=True), 'baseline_min_rescaled': FieldInfo(annotation=bool, required=True), 'bin_baseline': FieldInfo(annotation=list, required=True), 'bin_insitu': FieldInfo(annotation=list, required=True), 'bin_presitu': FieldInfo(annotation=list, required=True), 'bin_wavelength': FieldInfo(annotation=list, required=True), 'insitu_max_rescaled': FieldInfo(annotation=bool, required=True), 'insitu_min_rescaled': FieldInfo(annotation=bool, required=True), 'lower_wl_idx': FieldInfo(annotation=int, required=True), 'mean_abs_omT_diff': FieldInfo(annotation=float, required=True), 'mean_abs_omT_ratio': FieldInfo(annotation=float, required=True), 'mean_ref_dark': FieldInfo(annotation=list, required=True), 'mean_ref_light': FieldInfo(annotation=list, required=True), 'noagg_epoch': FieldInfo(annotation=list, required=True), 'noagg_omt_baseline': FieldInfo(annotation=list, required=True), 'noagg_omt_insitu': FieldInfo(annotation=list, required=True), 'noagg_omt_presitu': FieldInfo(annotation=list, required=True), 'noagg_omt_ratio': FieldInfo(annotation=list, required=True), 'noagg_presitu_epoch': FieldInfo(annotation=list, required=True), 'noagg_presitu_wavelength': FieldInfo(annotation=list, required=True), 'noagg_wavelength': FieldInfo(annotation=list, required=True), 'presitu_max_rescaled': FieldInfo(annotation=bool, required=True), 'presitu_min_rescaled': FieldInfo(annotation=bool, required=True), 'rscl_baseline': FieldInfo(annotation=list, required=True), 'rscl_insitu': FieldInfo(annotation=list, required=True), 'rscl_presitu': FieldInfo(annotation=list, required=True), 'smth_baseline': FieldInfo(annotation=list, required=True), 'smth_insitu': FieldInfo(annotation=list, required=True), 'smth_presitu': FieldInfo(annotation=list, required=True), 'upper_wl_idx': FieldInfo(annotation=int, required=True), 'wavelength': FieldInfo(annotation=list, required=True)}*

Metadata about the fields defined on the model,
mapping of field names to [FieldInfo][pydantic.fields.FieldInfo] objects.

This replaces Model._\_fields_\_ from Pydantic V1.

#### noagg_epoch *: `list`*

#### noagg_omt_baseline *: `list`*

#### noagg_omt_insitu *: `list`*

#### noagg_omt_presitu *: `list`*

#### noagg_omt_ratio *: `list`*

#### noagg_presitu_epoch *: `list`*

#### noagg_presitu_wavelength *: `list`*

#### noagg_wavelength *: `list`*

#### presitu_max_rescaled *: `bool`*

#### presitu_min_rescaled *: `bool`*

#### rscl_baseline *: `list`*

#### rscl_insitu *: `list`*

#### rscl_presitu *: `list`*

#### smth_baseline *: `list`*

#### smth_insitu *: `list`*

#### smth_presitu *: `list`*

#### upper_wl_idx *: `int`*

#### wavelength *: `list`*

### helao.drivers.data.analyses.echeuvis_stability.parse_spechlo(hlod)

Read spectrometer hlo into wavelength, epoch, spectra tuple.

### helao.drivers.data.analyses.echeuvis_stability.refadjust(v, min_mthd_allowed, max_mthd_allowed, min_limit, max_limit)

Normalization func from JCAPDataProcess uvis_basics.py, updated for array ops.

## helao.drivers.data.analyses.icpms_local module

### *class* helao.drivers.data.analyses.icpms_local.IcpmsAnalysis(process_uuid, local_loader, analysis_params)

Bases: [`BaseAnalysis`](#helao.drivers.data.analyses.base_analysis.BaseAnalysis)

Dry UVIS Analysis for GCLD demonstration.

#### \_\_init_\_(process_uuid, local_loader, analysis_params)

#### analysis_codehash *: `str`*

#### analysis_name *: `str`*

#### analysis_params *: `dict`*

#### analysis_timestamp *: `datetime`*

#### analysis_uuid *: `UUID`*

#### calc_output()

Calculate stability FOMs and intermediate vectors.

#### global_sample_label *: `str`*

#### inputs *: `AnalysisInput`*

#### outputs *: [`IcpmsOutputs`](#helao.drivers.data.analyses.icpms_local.IcpmsOutputs)*

#### process_name *: `str`*

#### process_timestamp *: `datetime`*

#### process_uuid *: `UUID`*

#### run_type *: `str`*

#### technique_name *: `str`*

### *class* helao.drivers.data.analyses.icpms_local.IcpmsInputs(process_uuid, local_loader)

Bases: `AnalysisInput`

#### \_\_init_\_(process_uuid, local_loader)

#### get_datamodels(\*args, \*\*kwargs)

* **Return type:**
  `List`[`AnalysisDataModel`]

#### global_sample_label *: `str`*

#### icpms *: [`HelaoProcess`](helao.drivers.data.loaders.md#helao.drivers.data.loaders.localfs.HelaoProcess)*

#### icpms_act *: [`HelaoAction`](helao.drivers.data.loaders.md#helao.drivers.data.loaders.localfs.HelaoAction)*

#### *property* mass_spec

#### process_params *: `dict`*

### *class* helao.drivers.data.analyses.icpms_local.IcpmsOutputs(\*\*data)

Bases: `BaseModel`

#### element *: `list`*

#### fom_key *: `str`*

#### global_sample_label *: `str`*

#### isotope *: `list`*

#### model_computed_fields *: ClassVar[Dict[str, ComputedFieldInfo]]* *= {}*

A dictionary of computed field names and their corresponding ComputedFieldInfo objects.

#### model_config *: ClassVar[ConfigDict]* *= {}*

Configuration for the model, should be a dictionary conforming to [ConfigDict][pydantic.config.ConfigDict].

#### model_fields *: ClassVar[Dict[str, FieldInfo]]* *= {'element': FieldInfo(annotation=list, required=True), 'fom_key': FieldInfo(annotation=str, required=True), 'global_sample_label': FieldInfo(annotation=str, required=True), 'isotope': FieldInfo(annotation=list, required=True), 'value': FieldInfo(annotation=list, required=True)}*

Metadata about the fields defined on the model,
mapping of field names to [FieldInfo][pydantic.fields.FieldInfo] objects.

This replaces Model._\_fields_\_ from Pydantic V1.

#### value *: `list`*

## helao.drivers.data.analyses.uvis_bkgsubnorm module

### *class* helao.drivers.data.analyses.uvis_bkgsubnorm.DryUvisAnalysis(process_uuid, query_df, analysis_params)

Bases: [`BaseAnalysis`](#helao.drivers.data.analyses.base_analysis.BaseAnalysis)

Dry UVIS Analysis for GCLD demonstration.

#### \_\_init_\_(process_uuid, query_df, analysis_params)

#### action_attr *: `str`*

#### analysis_codehash *: `str`*

#### analysis_name *: `str`*

#### analysis_params *: `dict`*

#### analysis_timestamp *: `datetime`*

#### analysis_uuid *: `UUID`*

#### calc_output()

Calculate stability FOMs and intermediate vectors.

#### inputs *: `AnalysisInput`*

#### outputs *: [`DryUvisOutputs`](#helao.drivers.data.analyses.uvis_bkgsubnorm.DryUvisOutputs)*

#### plate_id *: `int`*

#### process_name *: `str`*

#### process_timestamp *: `datetime`*

#### process_uuid *: `UUID`*

#### run_type *: `str`*

#### sample_no *: `int`*

#### technique_name *: `str`*

### *class* helao.drivers.data.analyses.uvis_bkgsubnorm.DryUvisInputs(insitu_process_uuid, plate_id, sample_no, query_df)

Bases: `AnalysisInput`

#### \_\_init_\_(insitu_process_uuid, plate_id, sample_no, query_df)

#### get_datamodels(global_sample_label, \*args, \*\*kwargs)

* **Return type:**
  `List`[`AnalysisDataModel`]

#### *property* insitu_spec

#### insitu_spec_act *: [`HelaoAction`](helao.drivers.data.loaders.md#helao.drivers.data.loaders.pgs3.HelaoAction)*

#### process_params *: `dict`*

#### *property* ref_dark_spec

#### ref_dark_spec_acts *: `List`[[`HelaoAction`](helao.drivers.data.loaders.md#helao.drivers.data.loaders.pgs3.HelaoAction)]*

#### ref_darks *: `List`[[`HelaoProcess`](helao.drivers.data.loaders.md#helao.drivers.data.loaders.pgs3.HelaoProcess)]*

#### *property* ref_light_spec

#### ref_light_spec_acts *: `List`[[`HelaoAction`](helao.drivers.data.loaders.md#helao.drivers.data.loaders.pgs3.HelaoAction)]*

#### ref_lights *: `List`[[`HelaoProcess`](helao.drivers.data.loaders.md#helao.drivers.data.loaders.pgs3.HelaoProcess)]*

### *class* helao.drivers.data.analyses.uvis_bkgsubnorm.DryUvisOutputs(\*\*data)

Bases: `BaseModel`

#### agg_insitu *: `list`*

#### agg_method *: `str`*

#### bin_insitu *: `list`*

#### bin_wavelength *: `list`*

#### insitu_max_rescaled *: `bool`*

#### insitu_min_rescaled *: `bool`*

#### lower_wl_idx *: `int`*

#### mean_ref_dark *: `list`*

#### mean_ref_light *: `list`*

#### model_computed_fields *: ClassVar[Dict[str, ComputedFieldInfo]]* *= {}*

A dictionary of computed field names and their corresponding ComputedFieldInfo objects.

#### model_config *: ClassVar[ConfigDict]* *= {}*

Configuration for the model, should be a dictionary conforming to [ConfigDict][pydantic.config.ConfigDict].

#### model_fields *: ClassVar[Dict[str, FieldInfo]]* *= {'agg_insitu': FieldInfo(annotation=list, required=True), 'agg_method': FieldInfo(annotation=str, required=True), 'bin_insitu': FieldInfo(annotation=list, required=True), 'bin_wavelength': FieldInfo(annotation=list, required=True), 'insitu_max_rescaled': FieldInfo(annotation=bool, required=True), 'insitu_min_rescaled': FieldInfo(annotation=bool, required=True), 'lower_wl_idx': FieldInfo(annotation=int, required=True), 'mean_ref_dark': FieldInfo(annotation=list, required=True), 'mean_ref_light': FieldInfo(annotation=list, required=True), 'rscl_insitu': FieldInfo(annotation=list, required=True), 'smth_insitu': FieldInfo(annotation=list, required=True), 'upper_wl_idx': FieldInfo(annotation=int, required=True), 'wavelength': FieldInfo(annotation=list, required=True)}*

Metadata about the fields defined on the model,
mapping of field names to [FieldInfo][pydantic.fields.FieldInfo] objects.

This replaces Model._\_fields_\_ from Pydantic V1.

#### rscl_insitu *: `list`*

#### smth_insitu *: `list`*

#### upper_wl_idx *: `int`*

#### wavelength *: `list`*

## Module contents
