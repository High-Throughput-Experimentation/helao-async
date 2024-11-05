# helao.drivers.data.loaders package

## Submodules

## helao.drivers.data.loaders.localfs module

### *class* helao.drivers.data.loaders.localfs.EcheUvisLoader(data_path)

Bases: [`LocalLoader`](#helao.drivers.data.loaders.localfs.LocalLoader)

ECHEUVIS process dataloader

#### \_\_init_\_(data_path)

#### get_recent(query, min_date='2023-04-26', plate_id=None, sample_no=None)

### *class* helao.drivers.data.loaders.localfs.HelaoAction(yml_path, meta_dict, loader)

Bases: [`HelaoModel`](#helao.drivers.data.loaders.localfs.HelaoModel)

#### \_\_init_\_(yml_path, meta_dict, loader)

#### action_name *: `str`*

#### action_params *: `dict`*

#### action_timestamp *: `datetime`*

#### action_uuid *: `UUID`*

#### *property* hlo

Retrieve json data from S3 via HelaoLoader.

#### *property* hlo_file

Return primary .hlo filename for this action.

#### *property* hlo_file_tup

Return primary .hlo filename, filetype, and data keys for this action.

#### read_hlo_file(filename)

### *class* helao.drivers.data.loaders.localfs.HelaoExperiment(yml_path, meta_dict, loader)

Bases: [`HelaoModel`](#helao.drivers.data.loaders.localfs.HelaoModel)

#### \_\_init_\_(yml_path, meta_dict, loader)

#### experiment_name *: `str`*

#### experiment_params *: `dict`*

#### experiment_timestamp *: `datetime`*

#### experiment_uuid *: `UUID`*

### *class* helao.drivers.data.loaders.localfs.HelaoModel(yml_path, meta_dict, loader)

Bases: `object`

#### \_\_init_\_(yml_path, meta_dict, loader)

#### helao_type *: `str`*

#### *property* json

#### name *: `str`*

#### params *: `dict`*

#### timestamp *: `datetime`*

#### uuid *: `UUID`*

### *class* helao.drivers.data.loaders.localfs.HelaoProcess(yml_path, meta_dict, loader)

Bases: [`HelaoModel`](#helao.drivers.data.loaders.localfs.HelaoModel)

#### \_\_init_\_(yml_path, meta_dict, loader)

#### process_params *: `dict`*

#### process_timestamp *: `datetime`*

#### process_uuid *: `UUID`*

#### technique_name *: `str`*

### *class* helao.drivers.data.loaders.localfs.HelaoSequence(yml_path, meta_dict, loader)

Bases: [`HelaoModel`](#helao.drivers.data.loaders.localfs.HelaoModel)

#### \_\_init_\_(yml_path, meta_dict, loader)

#### sequence_label *: `str`*

#### sequence_name *: `str`*

#### sequence_params *: `dict`*

#### sequence_timestamp *: `datetime`*

#### sequence_uuid *: `UUID`*

### *class* helao.drivers.data.loaders.localfs.LocalLoader(data_path)

Bases: `object`

Provides cached access to local data.

#### \_\_init_\_(data_path)

#### clear_cache()

#### get_act(index=None, path=None)

#### get_exp(index=None, path=None)

#### get_hlo(yml_path, hlo_fn)

#### get_prc(index=None, path=None)

#### get_seq(index=None, path=None)

#### get_yml(path)

## helao.drivers.data.loaders.pgs3 module

### *class* helao.drivers.data.loaders.pgs3.EcheUvisLoader(env_file='.env', cache_s3=False, cache_json=False, cache_sql=False)

Bases: [`HelaoLoader`](#helao.drivers.data.loaders.pgs3.HelaoLoader)

ECHEUVIS process dataloader

#### \_\_init_\_(env_file='.env', cache_s3=False, cache_json=False, cache_sql=False)

#### get_recent(query, min_date='2024-01-01', plate_id=None, sample_no=None, sql_query_retries=3)

#### get_sequence(query, sequence_uuid, sql_query_retries=5)

### *class* helao.drivers.data.loaders.pgs3.HelaoAction(uuid, query_df=None)

Bases: [`HelaoModel`](#helao.drivers.data.loaders.pgs3.HelaoModel)

#### \_\_init_\_(uuid, query_df=None)

#### action_name *: `str`*

#### action_params *: `dict`*

#### action_timestamp *: `datetime`*

#### action_uuid *: `UUID`*

#### *property* hlo

Retrieve json data from S3 via HelaoLoader.

#### *property* hlo_file

Return primary .hlo filename for this action.

#### *property* hlo_file_tup

Return primary .hlo filename, filetype, and data keys for this action.

### *class* helao.drivers.data.loaders.pgs3.HelaoExperiment(uuid, query_df=None)

Bases: [`HelaoModel`](#helao.drivers.data.loaders.pgs3.HelaoModel)

#### \_\_init_\_(uuid, query_df=None)

#### experiment_name *: `str`*

#### experiment_params *: `dict`*

#### experiment_timestamp *: `datetime`*

#### experiment_uuid *: `UUID`*

### *class* helao.drivers.data.loaders.pgs3.HelaoLoader(env_file='.env', cache_s3=False, cache_json=False, cache_sql=False)

Bases: `object`

Provides cached access to S3 and SQL

#### \_\_init_\_(env_file='.env', cache_s3=False, cache_json=False, cache_sql=False)

#### clear_cache()

#### connect()

#### get_act(action_uuid, hmod=True)

#### get_exp(experiment_uuid, hmod=True)

#### get_hlo(action_uuid, hlo_fn)

#### get_json(helao_type, uuid)

#### get_prc(process_uuid, hmod=True)

#### get_seq(sequence_uuid, hmod=True)

#### get_sql(helao_type, obj_uuid)

#### reconnect()

#### run_raw_query(query)

### *class* helao.drivers.data.loaders.pgs3.HelaoModel(helao_type, uuid, query_df=None)

Bases: `object`

#### \_\_init_\_(helao_type, uuid, query_df=None)

#### helao_type *: `str`*

#### *property* json

#### name *: `str`*

#### params *: `dict`*

#### timestamp *: `datetime`*

#### uuid *: `UUID`*

### *class* helao.drivers.data.loaders.pgs3.HelaoProcess(uuid, query_df=None)

Bases: [`HelaoModel`](#helao.drivers.data.loaders.pgs3.HelaoModel)

#### \_\_init_\_(uuid, query_df=None)

#### process_name *: `str`*

#### process_params *: `dict`*

#### process_timestamp *: `datetime`*

#### process_uuid *: `UUID`*

### *class* helao.drivers.data.loaders.pgs3.HelaoSequence(uuid, query_df=None)

Bases: [`HelaoModel`](#helao.drivers.data.loaders.pgs3.HelaoModel)

#### \_\_init_\_(uuid, query_df=None)

#### sequence_name *: `str`*

#### sequence_params *: `dict`*

#### sequence_timestamp *: `datetime`*

#### sequence_uuid *: `UUID`*

### *class* helao.drivers.data.loaders.pgs3.HelaoSolid(sample_label)

Bases: `object`

#### \_\_init_\_(sample_label)

#### sample_label *: `str`*

## Module contents
