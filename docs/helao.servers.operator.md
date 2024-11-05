# helao.servers.operator package

## Submodules

## helao.servers.operator.bokeh_operator module

This module defines the BokehOperator class, which is responsible for managing
the Bokeh-based user interface for the HTE (High Throughput Experimentation) 
orchestrator. The BokehOperator class provides methods for interacting with 
the orchestrator, including adding sequences and experiments, updating tables, 
and handling user input.

Classes:
: return_sequence_lib: A Pydantic BaseModel class representing a sequence 
  : object with attributes such as index, sequence_name, doc, args, 
    defaults, and argtypes.
  <br/>
  return_experiment_lib: A Pydantic BaseModel class representing an 
  : experiment object with attributes such as index, experiment_name, 
    doc, args, defaults, and argtypes.
  <br/>
  BokehOperator: A class that manages the Bokeh-based user interface for 
  : the HTE orchestrator. It provides methods for interacting with the 
    orchestrator, updating tables, handling user input, and managing 
    sequences and experiments.

### *class* helao.servers.operator.bokeh_operator.BokehOperator(vis_serv, orch)

Bases: `object`

#### *async* IOloop()

#### \_\_init_\_(vis_serv, orch)

#### add_dynamic_inputs(param_input, private_input, param_layout, args, defaults, argtypes)

#### *async* add_experiment_to_sequence()

#### append_experiment()

#### callback_add_expplan(event)

add experiment plan as new sequence to orch sequence_dq

#### callback_append_exp(event)

#### callback_append_seq(event)

#### callback_changed_plateid(attr, old, new, sender)

callback for plateid text input

#### callback_changed_sampleno(attr, old, new, sender)

callback for sampleno text input

#### callback_clear_actions(event)

#### callback_clear_experiments(event)

#### callback_clear_expplan(event)

#### callback_clear_sequences(event)

#### callback_clicked_pmplot(event, sender)

double click/tap on PM plot to add/move marker

#### callback_copy_sequence_comment(attr, old, new)

#### callback_copy_sequence_comment2(attr, old, new)

#### callback_copy_sequence_label(attr, old, new)

#### callback_copy_sequence_label2(attr, old, new)

#### callback_enqueue_seqspec(event)

#### callback_estop_orch(event)

#### callback_experiment_select(attr, old, new)

#### callback_plate_sample_no_list_file(attr, old, new, sender, inputfield)

#### callback_prepend_exp(event)

#### callback_prepend_seq(event)

#### callback_reload_seqspec(event)

#### callback_seqspec_select(attr, old, new)

#### callback_sequence_select(attr, old, new)

#### callback_skip_exp(event)

#### callback_start_orch(event)

#### callback_stop_orch(event)

#### callback_to_seqtab(event)

#### callback_toggle_stepact(event)

#### callback_toggle_stepexp(event)

#### callback_toggle_stepseq(event)

#### callback_update_tables(event)

#### cleanup_session(session_context)

#### find_input(inputs, name)

#### find_param_private_input(sender)

#### find_plot(inputs, name)

#### flip_stepwise_flag(sender_type)

#### *async* get_actions()

get action list from orch

#### *async* get_active_actions()

get action list from orch

#### get_elements_plateid(plateid, sender)

gets plate elements from aligner server

#### get_experiment_lib()

Populates experiments (library) and experiment_list (dropdown selector).

#### *async* get_experiments()

get experiment list from orch

#### get_last_exp_pars()

#### get_last_seq_pars()

#### *async* get_orch_status_summary()

#### get_pm(plateid, sender)

gets plate map

#### get_sample_infos(PMnum=None, sender=None)

#### get_samples(X, Y, sender)

get list of samples row number closest to xy

#### get_seqspec_lib()

Populates sequence specification library (preset params) and dropdown.

#### get_sequence_lib()

Populates sequences (library) and sequence_list (dropdown selector).

#### *async* get_sequences()

get experiment list from orch

#### populate_experimentmodel()

* **Return type:**
  `ExperimentModel`

#### populate_sequence()

#### prepend_experiment()

#### read_params(ptype, name)

#### refresh_inputs(param_input, private_input)

#### update_error(value)

#### update_exp_doc(value)

#### update_exp_param_layout(idx)

#### update_input_value(sender, value)

#### update_pm_plot(plot_mpmap, pmdata)

plots the plate map

#### update_queuecount_labels()

#### update_selector_layout(attr, old, new)

#### update_seq_doc(value)

#### update_seq_param_layout(idx)

#### update_seqspec_doc(value)

#### update_seqspec_param_layout(idx)

#### update_stepwise_toggle(sender)

#### *async* update_tables()

#### update_xysamples(xval, yval, sender)

#### write_params(ptype, name, pars)

#### xy_to_sample(xy, pmapxy)

get point from pmap closest to xy

### *class* helao.servers.operator.bokeh_operator.return_experiment_lib(\*\*data)

Bases: `BaseModel`

Return class for queried experiment objects.

#### args *: `list`*

#### argtypes *: `list`*

#### defaults *: `list`*

#### doc *: `str`*

#### experiment_name *: `str`*

#### index *: `int`*

#### model_computed_fields *: ClassVar[Dict[str, ComputedFieldInfo]]* *= {}*

A dictionary of computed field names and their corresponding ComputedFieldInfo objects.

#### model_config *: ClassVar[ConfigDict]* *= {}*

Configuration for the model, should be a dictionary conforming to [ConfigDict][pydantic.config.ConfigDict].

#### model_fields *: ClassVar[Dict[str, FieldInfo]]* *= {'args': FieldInfo(annotation=list, required=True), 'argtypes': FieldInfo(annotation=list, required=True), 'defaults': FieldInfo(annotation=list, required=True), 'doc': FieldInfo(annotation=str, required=True), 'experiment_name': FieldInfo(annotation=str, required=True), 'index': FieldInfo(annotation=int, required=True)}*

Metadata about the fields defined on the model,
mapping of field names to [FieldInfo][pydantic.fields.FieldInfo] objects.

This replaces Model._\_fields_\_ from Pydantic V1.

### *class* helao.servers.operator.bokeh_operator.return_sequence_lib(\*\*data)

Bases: `BaseModel`

Return class for queried sequence objects.

#### args *: `list`*

#### argtypes *: `list`*

#### defaults *: `list`*

#### doc *: `str`*

#### index *: `int`*

#### model_computed_fields *: ClassVar[Dict[str, ComputedFieldInfo]]* *= {}*

A dictionary of computed field names and their corresponding ComputedFieldInfo objects.

#### model_config *: ClassVar[ConfigDict]* *= {}*

Configuration for the model, should be a dictionary conforming to [ConfigDict][pydantic.config.ConfigDict].

#### model_fields *: ClassVar[Dict[str, FieldInfo]]* *= {'args': FieldInfo(annotation=list, required=True), 'argtypes': FieldInfo(annotation=list, required=True), 'defaults': FieldInfo(annotation=list, required=True), 'doc': FieldInfo(annotation=str, required=True), 'index': FieldInfo(annotation=int, required=True), 'sequence_name': FieldInfo(annotation=str, required=True)}*

Metadata about the fields defined on the model,
mapping of field names to [FieldInfo][pydantic.fields.FieldInfo] objects.

This replaces Model._\_fields_\_ from Pydantic V1.

#### sequence_name *: `str`*

## helao.servers.operator.finish_analysis module

## helao.servers.operator.gcld_operator module

### helao.servers.operator.gcld_operator.ana_constructor(plate_id, sequence_uuid, data_request_id, params={}, seq_func=<function UVIS_T_postseq>, seq_name='UVIS_T_postseq', seq_label='gcld-mvp-demo-analysis', param_defaults={})

### helao.servers.operator.gcld_operator.gen_ts()

### helao.servers.operator.gcld_operator.main()

### helao.servers.operator.gcld_operator.num_uploads(db_cfg)

### helao.servers.operator.gcld_operator.qc_constructor(plate_id, sample_no, data_request_id, params={}, seq_func=<function UVIS_T>, seq_name='UVIS_T', seq_label='gcld-mvp-demo', param_defaults={})

### helao.servers.operator.gcld_operator.seq_constructor(plate_id, sample_no, data_request_id, params={}, seq_func=<function UVIS_T>, seq_name='UVIS_T', seq_label='gcld-mvp-demo', param_defaults={})

### helao.servers.operator.gcld_operator.wait_for_orch(op, loop_state=LoopStatus.started, polling_time=5.0)

## helao.servers.operator.gcld_operator_test module

## helao.servers.operator.helao_operator module

### *class* helao.servers.operator.helao_operator.HelaoOperator(config_arg, orch_key)

Bases: `object`

HelaoOperator class to interact with the orchestrator server.

Attributes:
: helao_config (dict): Configuration loaded for Helao.
  orch_key (str): Key for the orchestrator server.
  orch_host (str): Host address of the orchestrator server.
  orch_port (int): Port number of the orchestrator server.

Methods:
: \_\_init_\_(config_arg, orch_key):
  : Initializes the HelaoOperator with the given configuration and orchestrator key.
  <br/>
  request(endpoint: str, path_params: dict = {}, json_params: dict = {}):
  : Sends a request to the orchestrator server and returns the response.
  <br/>
  start():
  : Dispatches a start request to the orchestrator server.
  <br/>
  stop():
  : Dispatches a stop request to the orchestrator server.
  <br/>
  orch_state():
  : Retrieves the current state of the orchestrator.
  <br/>
  get_active_experiment():
  : Retrieves the currently active experiment.
  <br/>
  get_active_sequence():
  : Retrieves the currently active sequence.
  <br/>
  add_experiment(experiment: Experiment, index: int = -1):
  : Adds an experiment to the active sequence or creates a new sequence.
  <br/>
  add_sequence(sequence: Sequence):
  : Adds a sequence to the orchestrator queue.

#### \_\_init_\_(config_arg, orch_key)

Initializes the HelaoOperator instance.

Args:
: config_arg (str): The configuration argument to load the configuration.
  orch_key (str): The key to identify the orchestrator server in the configuration.

Raises:
: Exception: If the orchestrator server is not found in the configuration.
  Exception: If the orchestrator host or port is not fully specified.

Attributes:
: helao_config (dict): The loaded configuration for Helao.
  orch_key (str): The key for the orchestrator server.
  orch_host (str): The host address of the orchestrator server.
  orch_port (int): The port number of the orchestrator server.

#### add_experiment(experiment, index=-1)

Adds an experiment to the operator’s experiment list.

If the index is -1, the experiment is appended to the end of the list.
Otherwise, the experiment is inserted at the specified index.

Args:
: experiment (Experiment): The experiment to be added.
  index (int, optional): The position at which to insert the experiment. Defaults to -1.

Returns:
: Response: The response from the request to add the experiment.

#### add_sequence(sequence)

Adds a sequence to the operator.

Args:
: sequence (Sequence): The sequence object to be added. It should have a method as_dict 
  : that converts the sequence to a dictionary format.

Returns:
: Response: The response from the request to append the sequence.

#### get_active_experiment()

Retrieve the currently active experiment.

This method sends a request to obtain the active experiment.

Returns:
: The active experiment data.

#### get_active_sequence()

Retrieve the currently active sequence.

This method sends a request to obtain the active sequence.

Returns:
: The active sequence.

#### orch_state()

Retrieve the current state of the orchestrator.

This method sends a request to get the current state of the orchestrator
and returns the response.

Returns:
: The current state of the orchestrator.

#### request(endpoint, path_params={}, json_params={})

Sends a request to the specified endpoint with given path and JSON parameters.

Args:
: endpoint (str): The endpoint to send the request to.
  path_params (dict, optional): The path parameters to include in the request. Defaults to {}.
  json_params (dict, optional): The JSON parameters to include in the request. Defaults to {}.

Returns:
: dict: The response from the request. If an exception occurs, returns a dictionary with 
  : “orch_state”, “loop_state”, and “loop_intent” set to “unreachable”.

#### start()

Initiates the ‘start’ request to the operator server.

Returns:
: Response from the ‘start’ request.

#### stop()

Sends a request to stop the current operation.

Returns:
: Response from the “stop” request.

## Module contents
