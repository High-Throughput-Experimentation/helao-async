# helao.helpers package

## Submodules

## helao.helpers.active_params module

### *class* helao.helpers.active_params.ActiveParams(\*\*data)

Bases: `BaseModel`, `HelaoDict`

ActiveParams is a model that represents the parameters for an active action.

Attributes:
: action (Action): The Action object for this action.
  file_conn_params_dict (Dict[UUID, FileConnParams]): A dictionary keyed by file_conn_key of FileConnParams for all files of active.
  aux_listen_uuids (List[UUID]): A list of UUIDs for auxiliary listeners.

Config:
: arbitrary_types_allowed (bool): Allows arbitrary types for model attributes.

Methods:
: validate_action(cls, v): Validator method for the action attribute.

#### *class* Config

Bases: `object`

#### arbitrary_types_allowed *= True*

#### action *: [`Action`](#helao.helpers.premodels.Action)*

#### aux_listen_uuids *: `List`[`UUID`]*

#### file_conn_params_dict *: `Dict`[`UUID`, `FileConnParams`]*

#### model_computed_fields *: ClassVar[Dict[str, ComputedFieldInfo]]* *= {}*

A dictionary of computed field names and their corresponding ComputedFieldInfo objects.

#### model_config *: ClassVar[ConfigDict]* *= {'arbitrary_types_allowed': True}*

Configuration for the model, should be a dictionary conforming to [ConfigDict][pydantic.config.ConfigDict].

#### model_fields *: ClassVar[Dict[str, FieldInfo]]* *= {'action': FieldInfo(annotation=Action, required=True), 'aux_listen_uuids': FieldInfo(annotation=List[UUID], required=False, default=[]), 'file_conn_params_dict': FieldInfo(annotation=Dict[UUID, FileConnParams], required=False, default={})}*

Metadata about the fields defined on the model,
mapping of field names to [FieldInfo][pydantic.fields.FieldInfo] objects.

This replaces Model._\_fields_\_ from Pydantic V1.

#### *classmethod* validate_action(v)

Validates the given action.

Args:
: v: The action to be validated.

Returns:
: The validated action.

## helao.helpers.bubble_detection module

### helao.helpers.bubble_detection.bubble_detection(data, RSD_threshold, simple_threshold, signal_change_threshold, amplitude_threshold)

data must be pd.Dataframe with t, and E column

* **Return type:**
  `bool`

## helao.helpers.config_loader module

### helao.helpers.config_loader.config_loader(confArg, helao_root)

Loads a configuration file in either Python (.py) or YAML (.yml) format.

Args:
: confArg (str): The path to the configuration file or a prefix for the configuration file.
  helao_root (str): The root directory for the helao project.

Returns:
: dict: The loaded configuration dictionary with an additional key ‘loaded_config_path’ 
  : indicating the absolute path of the loaded configuration file.

Raises:
: FileNotFoundError: If the specified configuration file does not exist or if the prefix 
  : does not correspond to an existing .py or .yml file.

## helao.helpers.dispatcher module

### *async* helao.helpers.dispatcher.async_action_dispatcher(world_config_dict, A, params={})

Asynchronously dispatches an action to the specified server and handles the response.

Args:
: world_config_dict (dict): A dictionary containing the configuration of the world, including server details.
  A (Action): An instance of the Action class containing details about the action to be dispatched.
  params (dict, optional): Additional parameters to be sent with the request. Defaults to an empty dictionary.

Returns:
: tuple: A tuple containing the response from the server (or None if an error occurred) and an error code indicating the status of the request.

Raises:
: Exception: If there is an issue with the request or response handling, an exception is caught and logged.

### *async* helao.helpers.dispatcher.async_private_dispatcher(server_key, host, port, private_action, params_dict={}, json_dict={})

Asynchronously dispatches a private action to a specified server.

Args:
: server_key (str): The key identifying the server.
  host (str): The host address of the server.
  port (int): The port number of the server.
  private_action (str): The private action to be dispatched.
  params_dict (dict, optional): The dictionary of parameters to be sent in the request. Defaults to {}.
  json_dict (dict, optional): The dictionary of JSON data to be sent in the request. Defaults to {}.

Returns:
: tuple: A tuple containing the response from the server and an error code.

### helao.helpers.dispatcher.private_dispatcher(server_key, server_host, server_port, private_action, params_dict={}, json_dict={})

Sends a POST request to a specified server and handles the response.

Args:
: server_key (str): Identifier for the server.
  server_host (str): Hostname or IP address of the server.
  server_port (int): Port number of the server.
  private_action (str): The action to be performed on the server.
  params_dict (dict, optional): Dictionary of URL parameters to append to the URL. Defaults to {}.
  json_dict (dict, optional): Dictionary to send in the body of the POST request as JSON. Defaults to {}.

Returns:
: tuple: A tuple containing the response (either as a JSON object or string) and an error code.

## helao.helpers.eval module

### helao.helpers.eval.eval_array(x)

Evaluates each element in the input array using the eval_val function and returns a new array with the evaluated values.

Args:
: x (list): A list of elements to be evaluated.

Returns:
: list: A list containing the evaluated values of the input elements.

### helao.helpers.eval.eval_val(x)

Evaluates and converts a given value based on its type.

Parameters:
x (any): The value to be evaluated. It can be of type list, dict, str, or any other type.

Returns:
any: The evaluated value. The return type depends on the input:

> - If the input is a list, it calls eval_array on the list.
> - If the input is a dict, it recursively evaluates each value in the dict.
> - If the input is a str, it attempts to convert it to an int, float, boolean, or NaN if applicable.
> - Otherwise, it returns the input value as is.

## helao.helpers.executor module

### *class* helao.helpers.executor.Executor(active, poll_rate=0.2, oneoff=True, exec_id=None, concurrent=True, \*\*kwargs)

Bases: `object`

Executor class for managing and executing asynchronous tasks with customizable setup, execution, polling, and cleanup methods.

Attributes:
: active: The active task or action to be executed.
  poll_rate (float): The rate at which polling occurs, in seconds.
  oneoff (bool): Indicates if the task is a one-time execution.
  exec_id (str): Unique identifier for the executor instance.
  concurrent (bool): Indicates if multiple executors can run concurrently.
  start_time (float): The start time of the execution.
  duration (float): The duration of the action, default is -1 (indefinite).

Methods:
: \_\_init_\_(self, active, poll_rate=0.2, oneoff=True, exec_id=None, concurrent=True, 
  <br/>
  ```
  **
  ```
  <br/>
  kwargs):
  : Initializes the Executor instance with the given parameters.
  <br/>
  async \_pre_exec(self):
  : Performs setup methods before execution. Returns error state.
  <br/>
  set_pre_exec(self, pre_exec_func):
  : Overrides the generic setup method with a custom function.
  <br/>
  async \_exec(self):
  : Performs the main execution of the task. Returns data and error state.
  <br/>
  set_exec(self, exec_func):
  : Overrides the generic execute method with a custom function.
  <br/>
  async \_poll(self):
  : Performs one polling iteration. Returns data, error state, and status.
  <br/>
  set_poll(self, poll_func):
  : Overrides the generic polling method with a custom function.
  <br/>
  async \_post_exec(self):
  : Performs cleanup methods after execution. Returns error state.
  <br/>
  set_post_exec(self, post_exec_func):
  : Overrides the generic cleanup method with a custom function.
  <br/>
  async \_manual_stop(self):
  : Performs manual stop of the device. Returns error state.
  <br/>
  set_manual_stop(self, manual_stop_func):
  : Overrides the generic manual stop method with a custom function.

#### \_\_init_\_(active, poll_rate=0.2, oneoff=True, exec_id=None, concurrent=True, \*\*kwargs)

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

#### set_exec(exec_func)

Sets the execution function for the instance.

Args:
: exec_func (function): The function to be set as the execution method.

#### set_manual_stop(manual_stop_func)

Sets a manual stop function for the executor.

Args:
: manual_stop_func (function): A function that will be used to manually stop the executor. 
  : This function should take no arguments.

#### set_poll(poll_func)

Sets the polling function for the executor.

Args:
: poll_func (function): A function to be used for polling. This function
  : should accept no arguments and will be bound to
    the instance of the executor.

#### set_post_exec(post_exec_func)

Sets the post-execution function.

This method assigns a given function to be executed after the main execution.

Args:
: post_exec_func (function): A function to be set as the post-execution function.

#### set_pre_exec(pre_exec_func)

Sets the pre-execution function.

This method assigns a function to be executed before the main execution.

Args:
: pre_exec_func (function): A function to be executed before the main execution.

## helao.helpers.file_in_use module

### helao.helpers.file_in_use.file_in_use(file_path)

## helao.helpers.file_mapper module

### *class* helao.helpers.file_mapper.FileMapper(save_path)

Bases: `object`

FileMapper is a class that helps in mapping and locating files within a specified directory structure.
It provides methods to locate, read, and process files based on their paths and states.

Attributes:
: inputfile (Path or None): The absolute path of the input file if it exists, otherwise None.
  inputdir (Path): The absolute path of the input directory.
  inputparts (list): A list of parts of the input directory path.
  runpos (int): The position of the “RUNS_\*” or “PROCESSES” directory in the path.
  prestr (str): The path string up to the “RUNS_\*” or “PROCESSES” directory.
  states (list): A list of states used to identify different run directories.
  relstrs (list): A list of relative paths of files within the “RUNS_\*” or “PROCESSES” directories.

Methods:
: \_\_init_\_(save_path: Union[str, Path]):
  : Initializes the FileMapper with the given save path.
  <br/>
  locate(p: str) -> Union[str, None]:
  : Locates the file path based on the given relative path and returns the absolute path if found.
  <br/>
  read_hlo(p: str, retries: int = 3) -> Union[tuple, None]:
  : Reads an HLO file from the given relative path with a specified number of retries.
  <br/>
  read_yml(p: str) -> dict:
  : Reads a YAML file from the given relative path and returns its contents as a dictionary.
  <br/>
  read_lines(p: str) -> list:
  : Reads a text file from the given relative path and returns its contents as a list of lines.
  <br/>
  read_bytes(p: str) -> bytes:
  : Reads a binary file from the given relative path and returns its contents as bytes.

#### \_\_init_\_(save_path)

Initializes the FileMapper object with the given save path.

Args:
: save_path (Union[str, Path]): The path where files are saved. It can be a string or a Path object.

Attributes:
: inputfile (Path or None): The absolute path of the input file if save_path is a file, otherwise None.
  inputdir (Path): The absolute path of the directory containing the input file or the save_path directory.
  inputparts (list): A list of parts of the input directory path.
  runpos (int): The position of the “RUNS_\*” or “PROCESSES” directory in the input directory path.
  prestr (str): The path string up to the “RUNS_\*” or “PROCESSES” directory.
  states (list): A list of states used to identify different run states.
  relstrs (list): A list of relative paths of all files at the save_path level and deeper, relative to “RUNS_\*” or “PROCESSES”.

#### locate(p)

Locate the file path based on the given string p.

This method checks if the string p contains the substring “PROCESSES”.
If it does, the method returns p as is. Otherwise, it iterates through
the states attribute, constructs a potential file path by joining
prestr, “

```
RUNS_
```

” followed by the current state, and p. If the constructed
path exists, it returns this path. If no valid path is found, it returns None.

Args:
: p (str): The file path or partial file path to locate.

Returns:
: str or None: The located file path if found, otherwise None.

#### read_bytes(p)

Reads the content of a file as bytes.

Args:
: p (str): The path to the file.

Returns:
: bytes: The content of the file.

Raises:
: FileNotFoundError: If the file cannot be located.

#### read_hlo(p, retries=3)

Reads an HLO file from the specified path with retry logic.

Args:
: p (str): The path to the HLO file.
  retries (int, optional): The number of times to retry reading the file in case of a ValueError. Defaults to 3.

Returns:
: tuple: The contents of the HLO file if read successfully.

Raises:
: FileNotFoundError: If the file cannot be located.
  ValueError: If the file cannot be read after the specified number of retries.

#### read_lines(p)

Reads the contents of a file and returns them as a list of lines.

Args:
: p (str): The path to the file.

Returns:
: list: A list of strings, each representing a line in the file.

Raises:
: FileNotFoundError: If the file cannot be located.

#### read_yml(p)

Reads a YAML file from the specified path and returns its contents as a dictionary.

Args:
: p (str): The path to the YAML file.

Returns:
: dict: The contents of the YAML file as a dictionary.

Raises:
: FileNotFoundError: If the file cannot be located.

## helao.helpers.gcld_client module

## helao.helpers.gen_uuid module

### helao.helpers.gen_uuid.gen_uuid(input=None)

Generate a uuid, encode with larger character set, and trucate.

## helao.helpers.helao_dirs module

### helao.helpers.helao_dirs.helao_dirs(world_cfg, server_name=None)

Initializes and verifies the directory structure for the Helao application based on the provided configuration.

* **Return type:**
  `HelaoDirs`

Args:
: world_cfg (dict): Configuration dictionary containing the root directory and other settings.
  server_name (str, optional): Name of the server. If provided, old log files will be compressed.

Returns:
: HelaoDirs: An instance of the HelaoDirs class containing paths to various directories.

Raises:
: Exception: If there is an error compressing old log files.

## helao.helpers.import_experiments module

### helao.helpers.import_experiments.import_experiments(world_config_dict, experiment_path=None, server_name='', user_experiment_path=None)

Import experiment functions into environment.

## helao.helpers.import_sequences module

### helao.helpers.import_sequences.import_sequences(world_config_dict, sequence_path=None, server_name='', user_sequence_path=None)

Import sequence functions into environment.

## helao.helpers.legacy_api module

### *class* helao.helpers.legacy_api.HTELegacyAPI(Serv_class)

Bases: `object`

#### \_\_init_\_(Serv_class)

#### check_annealrecord_plateid(plateid)

#### check_plateid(plateid)

#### check_printrecord_plateid(plateid)

#### createdict_tup(nam_listtup)

#### createnestparamtup(lines)

#### filedict_lines(lines)

#### get_elements_plateid(plateid, multielementink_concentrationinfo_bool=False, print_key_or_keyword='screening_print_id', exclude_elements_list=[''], return_defaults_if_none=False)

#### get_info_plateid(plateid)

#### get_multielementink_concentrationinfo(printd, els, return_defaults_if_none=False)

#### get_platemap_plateid(plateid)

#### get_rcp_plateid(plateid)

#### getinfopath_plateid(plateid, erroruifcn=None)

#### getnumspaces(a)

#### getplatemappath_plateid(plateid, erroruifcn=None, infokey='screening_map_id:', return_pmidstr=False, pmidstr=None)

#### importinfo(plateid)

#### myeval(c)

#### partitionlineitem(ln)

#### rcp_to_dict(rcppath)

#### readsingleplatemaptxt(p, returnfiducials=False, erroruifcn=None, lines=None)

#### tryprependpath(preppendfolderlist, p, testfile=True, testdir=True)

## helao.helpers.logging module

Logging module, import at top of every script

Usage:

> from helao.helpers import logging
> if logging.LOGGER is None:

> > logger = logging.make_logger()

> logger = logging.LOGGER

### helao.helpers.logging.make_logger(logger_name=None, log_dir=None, log_level=20)

Creates and configures a logger instance with both console and file handlers.

Args:
: logger_name (Optional[str]): The name of the logger. If None, the root logger is used.
  log_dir (Optional[str]): The directory where the log file will be stored. If None, the system’s temporary directory is used.
  log_level (int): The logging level. Default is 20 (INFO). Other levels are 10 (DEBUG), 30 (WARNING), 40 (ERROR), 50 (CRITICAL).

Returns:
: logging.Logger: Configured logger instance.

## helao.helpers.make_str_enum module

### helao.helpers.make_str_enum.make_str_enum(name, valdict)

Dynamically creates a string-based enumeration.

Args:
: name (str): The name of the enumeration.
  valdict (dict): A dictionary where keys are the enumeration names and values are the corresponding string values.

Returns:
: Enum: A new enumeration class with string values.

Example:
: ```pycon
  >>> Colors = make_str_enum('Colors', {'RED': 'red', 'GREEN': 'green', 'BLUE': 'blue'})
  >>> Colors.RED
  <Colors.RED: 'red'>
  >>> Colors.RED.value
  'red'
  ```

## helao.helpers.multisubscriber_queue module

### *class* helao.helpers.multisubscriber_queue.MultisubscriberQueue(\*\*kwargs)

Bases: `object`

MultisubscriberQueue is a class that allows multiple subscribers to receive data from a single source asynchronously.

Methods:
: \_\_init_\_(
  <br/>
  ```
  **
  ```
  <br/>
  kwargs):
  : Initializes the MultisubscriberQueue instance.
  <br/>
  \_\_len_\_():
  : Returns the number of subscribers.
  <br/>
  \_\_contains_\_(q):
  : Checks if a queue is in the list of subscribers.
  <br/>
  async subscribe():
  : Subscribes to data using an async generator. Instead of working with the Queue directly, the client can subscribe to data and have it yielded directly.
  <br/>
  queue():
  : Gets a new async Queue and adds it to the list of subscribers.
  <br/>
  queue_context():
  : Gets a new queue context wrapper. The queue context wrapper allows the queue to be automatically removed from the subscriber pool when the context is exited.
  <br/>
  remove(q):
  : Removes a queue from the pool of subscribers. Raises a KeyError if the queue does not exist.
  <br/>
  async put(data: Any):
  : Puts new data on all subscriber queues.
    : data: The data to be put on the queues.
  <br/>
  put_nowait(data: Any):
  : Puts new data on all subscriber queues without waiting.
    : data: The data to be put on the queues.
  <br/>
  async close():
  : Forces clients using MultisubscriberQueue.subscribe() to end iteration.

#### \_\_init_\_(\*\*kwargs)

Initializes a new instance of the class.

Keyword Args:
: ```
  **
  ```
  <br/>
  kwargs: Arbitrary keyword arguments.

#### *async* close()

Asynchronously closes the queue by putting a StopAsyncIteration exception into it.

This method should be called to signal that no more items will be added to the queue.

#### *async* put(data)

Asynchronously puts data into all subscriber queues.

Args:
: data (Any): The data to be put into the subscriber queues.

Returns:
: None

#### put_nowait(data)

Put data into all subscriber queues without blocking.

Args:
: data (Any): The data to be put into the subscriber queues.

#### queue()

Creates a new Queue instance, appends it to the subscribers list, and returns the Queue.

Returns:
: Queue: A new Queue instance that has been added to the subscribers list.

#### queue_context()

Provides a context manager for the queue.

Returns:
: \_QueueContext: A context manager instance for the queue.

#### remove(q)

Removes a subscriber queue from the list of subscribers.

Args:
: q: The subscriber queue to be removed.

Raises:
: KeyError: If the subscriber queue does not exist in the list of subscribers.

#### *async* subscribe()

Asynchronously subscribes to a queue and yields values from it.

This coroutine function enters a queue context and continuously retrieves
values from the queue. It yields each value until it encounters a 
StopAsyncIteration, at which point it breaks the loop and stops the 
subscription.

Yields:
: Any: The next value from the queue.

Raises:
: StopAsyncIteration: When the queue signals the end of iteration.

## helao.helpers.parquet module

This module provides helper functions to read HLO files, process their data, and convert them to Parquet format.

Functions:
: read_hlo_header(file_path):
  <br/>
  read_hlo_data_chunks(file_path, data_start_index, chunk_size=100):
  : Reads the data chunks from a HLO file starting from a given index.
  <br/>
  hlo_to_parquet(input_hlo_path, output_parquet_path, chunk_size=100):
  : Converts a HLO file to a Parquet file.
  <br/>
  read_helao_metadata(parquet_file_path):
  : Reads the custom metadata from a Parquet file.

### helao.helpers.parquet.hlo_to_parquet(input_hlo_path, output_parquet_path, chunk_size=100)

Converts HLO (custom format) data to Parquet format.

Parameters:
input_hlo_path (str): Path to the input HLO file.
output_parquet_path (str): Path to the output Parquet file.
chunk_size (int, optional): Number of rows to process at a time. Default is 100.

Returns:
None

### helao.helpers.parquet.read_helao_metadata(parquet_file_path)

Reads Helao metadata from a Parquet file.

Args:
: parquet_file_path (str): The file path to the Parquet file.

Returns:
: dict: A dictionary containing the Helao metadata.

### helao.helpers.parquet.read_hlo_data_chunks(file_path, data_start_index, chunk_size=100)

Reads data from a file in chunks and yields the data as dictionaries.

Args:
: file_path (str): The path to the file to read.
  data_start_index (int): The line index to start reading data from.
  chunk_size (int, optional): The number of lines to read in each chunk. Defaults to 100.

Yields:
: tuple: A tuple containing:
  : - dict: A dictionary where keys are the JSON keys from the file and values are lists of the corresponding values.
    - int: The maximum length of the lists in the dictionary.

### helao.helpers.parquet.read_hlo_header(file_path)

Reads the header of a HLO file and returns the parsed YAML content and the index where the data starts.

Args:
: file_path (str): The path to the HLO file.

Returns:
: tuple: A tuple containing:
  : - dict: Parsed YAML content from the header.
    - int: The index where the data starts in the file.

## helao.helpers.premodels module

schema.py
Standard classes for experiment queue objects.

### *class* helao.helpers.premodels.Action(\*\*data)

Bases: [`Experiment`](#helao.helpers.premodels.Experiment), `ActionModel`

Sample-action identifier class.

#### AUX_file_paths *: `List`[`Path`]*

#### data_stream_status *: `Optional`[`HloStatus`]*

#### file_conn_keys *: `List`[`UUID`]*

#### from_globalexp_params *: `Optional`[`dict`]*

#### get_action_dir()

#### get_actmodel()

#### init_act(time_offset=0, force=False)

#### model_computed_fields *: ClassVar[Dict[str, ComputedFieldInfo]]* *= {}*

A dictionary of computed field names and their corresponding ComputedFieldInfo objects.

#### model_config *: ClassVar[ConfigDict]* *= {}*

Configuration for the model, should be a dictionary conforming to [ConfigDict][pydantic.config.ConfigDict].

#### model_fields *: ClassVar[Dict[str, FieldInfo]]* *= {'AUX_file_paths': FieldInfo(annotation=List[Path], required=False, default=[]), 'access': FieldInfo(annotation=Union[str, NoneType], required=False, default='hte'), 'action_abbr': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'action_actual_order': FieldInfo(annotation=Union[int, NoneType], required=False, default=0), 'action_codehash': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'action_etc': FieldInfo(annotation=Union[float, NoneType], required=False, default=None), 'action_list': FieldInfo(annotation=List[ShortActionModel], required=False, default=[]), 'action_name': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'action_order': FieldInfo(annotation=Union[int, NoneType], required=False, default=0), 'action_output': FieldInfo(annotation=dict, required=False, default={}), 'action_output_dir': FieldInfo(annotation=Union[Path, NoneType], required=False, default=None), 'action_params': FieldInfo(annotation=dict, required=False, default={}), 'action_plan': FieldInfo(annotation=list, required=False, default=[]), 'action_retry': FieldInfo(annotation=Union[int, NoneType], required=False, default=0), 'action_server': FieldInfo(annotation=MachineModel, required=False, default=MachineModel(server_name=None, machine_name=None, hostname=None, port=None)), 'action_split': FieldInfo(annotation=Union[int, NoneType], required=False, default=0), 'action_status': FieldInfo(annotation=List[HloStatus], required=False, default=[]), 'action_sub_name': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'action_timestamp': FieldInfo(annotation=Union[datetime, NoneType], required=False, default=None), 'action_uuid': FieldInfo(annotation=Union[UUID, NoneType], required=False, default=None), 'actionmodel_list': FieldInfo(annotation=List[ActionModel], required=False, default=[]), 'child_action_uuid': FieldInfo(annotation=Union[UUID, NoneType], required=False, default=None), 'data_request_id': FieldInfo(annotation=Union[UUID, NoneType], required=False, default=None), 'data_stream_status': FieldInfo(annotation=Union[HloStatus, NoneType], required=False, default=None), 'dummy': FieldInfo(annotation=bool, required=False, default=False), 'error_code': FieldInfo(annotation=Union[ErrorCodes, NoneType], required=False, default=<ErrorCodes.none: 'none'>), 'exec_id': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'experiment_codehash': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'experiment_label': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'experiment_list': FieldInfo(annotation=List[ShortExperimentModel], required=False, default=[]), 'experiment_name': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'experiment_output_dir': FieldInfo(annotation=Union[Path, NoneType], required=False, default=None), 'experiment_params': FieldInfo(annotation=Union[dict, NoneType], required=False, default={}), 'experiment_plan_list': FieldInfo(annotation=List[ExperimentTemplate], required=False, default=[]), 'experiment_status': FieldInfo(annotation=List[HloStatus], required=False, default=[]), 'experiment_timestamp': FieldInfo(annotation=Union[datetime, NoneType], required=False, default=None), 'experiment_uuid': FieldInfo(annotation=Union[UUID, NoneType], required=False, default=None), 'experimentmodel_list': FieldInfo(annotation=List[ExperimentModel], required=False, default=[]), 'file_conn_keys': FieldInfo(annotation=List[UUID], required=False, default=[]), 'files': FieldInfo(annotation=List[FileInfo], required=False, default=[]), 'from_globalexp_params': FieldInfo(annotation=Union[dict, NoneType], required=False, default={}), 'hlo_version': FieldInfo(annotation=Union[str, NoneType], required=False, default_factory=get_hlo_version), 'manual_action': FieldInfo(annotation=bool, required=False, default=False), 'nonblocking': FieldInfo(annotation=bool, required=False, default=False), 'orch_host': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'orch_key': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'orch_port': FieldInfo(annotation=Union[int, NoneType], required=False, default=None), 'orch_submit_order': FieldInfo(annotation=Union[int, NoneType], required=False, default=0), 'orchestrator': FieldInfo(annotation=MachineModel, required=False, default=MachineModel(server_name=None, machine_name=None, hostname=None, port=None)), 'parent_action_uuid': FieldInfo(annotation=Union[UUID, NoneType], required=False, default=None), 'process_contrib': FieldInfo(annotation=List[ProcessContrib], required=False, default=[]), 'process_finish': FieldInfo(annotation=bool, required=False, default=False), 'process_list': FieldInfo(annotation=List[UUID], required=False, default=[]), 'process_order_groups': FieldInfo(annotation=Dict[int, List[int]], required=False, default={}), 'process_uuid': FieldInfo(annotation=Union[UUID, NoneType], required=False, default=None), 'run_type': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'run_use': FieldInfo(annotation=Union[RunUse, NoneType], required=False, default='data'), 'samples_in': FieldInfo(annotation=List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]], required=False, default=[]), 'samples_out': FieldInfo(annotation=List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]], required=False, default=[]), 'save_act': FieldInfo(annotation=bool, required=False, default=True), 'save_data': FieldInfo(annotation=bool, required=False, default=True), 'sequence_codehash': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'sequence_comment': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'sequence_label': FieldInfo(annotation=Union[str, NoneType], required=False, default='noLabel'), 'sequence_name': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'sequence_output_dir': FieldInfo(annotation=Union[Path, NoneType], required=False, default=None), 'sequence_params': FieldInfo(annotation=Union[dict, NoneType], required=False, default={}), 'sequence_status': FieldInfo(annotation=List[HloStatus], required=False, default=[]), 'sequence_timestamp': FieldInfo(annotation=Union[datetime, NoneType], required=False, default=None), 'sequence_uuid': FieldInfo(annotation=Union[UUID, NoneType], required=False, default=None), 'simulation': FieldInfo(annotation=bool, required=False, default=False), 'start_condition': FieldInfo(annotation=ActionStartCondition, required=False, default=<ActionStartCondition.wait_for_all: 3>), 'technique_name': FieldInfo(annotation=Union[str, list, NoneType], required=False, default=None), 'to_globalexp_params': FieldInfo(annotation=Union[list, dict, NoneType], required=False, default=[])}*

Metadata about the fields defined on the model,
mapping of field names to [FieldInfo][pydantic.fields.FieldInfo] objects.

This replaces Model._\_fields_\_ from Pydantic V1.

#### save_act *: `bool`*

#### save_data *: `bool`*

#### start_condition *: `ActionStartCondition`*

#### to_globalexp_params *: `Union`[`list`, `dict`, `None`]*

### *class* helao.helpers.premodels.ActionPlanMaker

Bases: `object`

#### \_\_init_\_()

#### add(action_server, action_name, action_params, start_condition=ActionStartCondition.wait_for_all, \*\*kwargs)

Shorthand add_action().

#### add_action(action_dict)

#### add_action_list(action_list)

#### *property* experiment

### *class* helao.helpers.premodels.Experiment(\*\*data)

Bases: [`Sequence`](#helao.helpers.premodels.Sequence), `ExperimentModel`

Sample-action grouping class.

#### action_plan *: `list`*

#### actionmodel_list *: `List`[`ActionModel`]*

#### from_globalexp_params *: `dict`*

#### get_exp()

#### get_experiment_dir()

accepts action or experiment object

#### init_exp(time_offset=0, force=False)

#### model_computed_fields *: ClassVar[Dict[str, ComputedFieldInfo]]* *= {}*

A dictionary of computed field names and their corresponding ComputedFieldInfo objects.

#### model_config *: ClassVar[ConfigDict]* *= {}*

Configuration for the model, should be a dictionary conforming to [ConfigDict][pydantic.config.ConfigDict].

#### model_fields *: ClassVar[Dict[str, FieldInfo]]* *= {'access': FieldInfo(annotation=Union[str, NoneType], required=False, default='hte'), 'action_list': FieldInfo(annotation=List[ShortActionModel], required=False, default=[]), 'action_plan': FieldInfo(annotation=list, required=False, default=[]), 'actionmodel_list': FieldInfo(annotation=List[ActionModel], required=False, default=[]), 'data_request_id': FieldInfo(annotation=Union[UUID, NoneType], required=False, default=None), 'dummy': FieldInfo(annotation=bool, required=False, default=False), 'experiment_codehash': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'experiment_label': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'experiment_list': FieldInfo(annotation=List[ShortExperimentModel], required=False, default=[]), 'experiment_name': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'experiment_output_dir': FieldInfo(annotation=Union[Path, NoneType], required=False, default=None), 'experiment_params': FieldInfo(annotation=Union[dict, NoneType], required=False, default={}), 'experiment_plan_list': FieldInfo(annotation=List[ExperimentTemplate], required=False, default=[]), 'experiment_status': FieldInfo(annotation=List[HloStatus], required=False, default=[]), 'experiment_timestamp': FieldInfo(annotation=Union[datetime, NoneType], required=False, default=None), 'experiment_uuid': FieldInfo(annotation=Union[UUID, NoneType], required=False, default=None), 'experimentmodel_list': FieldInfo(annotation=List[ExperimentModel], required=False, default=[]), 'files': FieldInfo(annotation=List[FileInfo], required=False, default=[]), 'from_globalexp_params': FieldInfo(annotation=dict, required=False, default={}), 'hlo_version': FieldInfo(annotation=Union[str, NoneType], required=False, default_factory=get_hlo_version), 'orch_host': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'orch_key': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'orch_port': FieldInfo(annotation=Union[int, NoneType], required=False, default=None), 'orchestrator': FieldInfo(annotation=MachineModel, required=False, default=MachineModel(server_name=None, machine_name=None, hostname=None, port=None)), 'process_list': FieldInfo(annotation=List[UUID], required=False, default=[]), 'process_order_groups': FieldInfo(annotation=Dict[int, List[int]], required=False, default={}), 'run_type': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'samples_in': FieldInfo(annotation=List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]], required=False, default=[]), 'samples_out': FieldInfo(annotation=List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]], required=False, default=[]), 'sequence_codehash': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'sequence_comment': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'sequence_label': FieldInfo(annotation=Union[str, NoneType], required=False, default='noLabel'), 'sequence_name': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'sequence_output_dir': FieldInfo(annotation=Union[Path, NoneType], required=False, default=None), 'sequence_params': FieldInfo(annotation=Union[dict, NoneType], required=False, default={}), 'sequence_status': FieldInfo(annotation=List[HloStatus], required=False, default=[]), 'sequence_timestamp': FieldInfo(annotation=Union[datetime, NoneType], required=False, default=None), 'sequence_uuid': FieldInfo(annotation=Union[UUID, NoneType], required=False, default=None), 'simulation': FieldInfo(annotation=bool, required=False, default=False)}*

Metadata about the fields defined on the model,
mapping of field names to [FieldInfo][pydantic.fields.FieldInfo] objects.

This replaces Model._\_fields_\_ from Pydantic V1.

### *class* helao.helpers.premodels.ExperimentPlanMaker

Bases: `object`

#### \_\_init_\_()

#### add_experiment(selected_experiment, experiment_params, \*\*kwargs)

### *class* helao.helpers.premodels.Sequence(\*\*data)

Bases: `SequenceModel`

Experiment grouping class.

#### experimentmodel_list *: `List`[`ExperimentModel`]*

#### from_globalexp_params *: `dict`*

#### get_seq()

#### get_sequence_dir()

#### init_seq(time_offset=0, force=False)

#### model_computed_fields *: ClassVar[Dict[str, ComputedFieldInfo]]* *= {}*

A dictionary of computed field names and their corresponding ComputedFieldInfo objects.

#### model_config *: ClassVar[ConfigDict]* *= {}*

Configuration for the model, should be a dictionary conforming to [ConfigDict][pydantic.config.ConfigDict].

#### model_fields *: ClassVar[Dict[str, FieldInfo]]* *= {'access': FieldInfo(annotation=Union[str, NoneType], required=False, default='hte'), 'data_request_id': FieldInfo(annotation=Union[UUID, NoneType], required=False, default=None), 'dummy': FieldInfo(annotation=bool, required=False, default=False), 'experiment_list': FieldInfo(annotation=List[ShortExperimentModel], required=False, default=[]), 'experiment_plan_list': FieldInfo(annotation=List[ExperimentTemplate], required=False, default=[]), 'experimentmodel_list': FieldInfo(annotation=List[ExperimentModel], required=False, default=[]), 'from_globalexp_params': FieldInfo(annotation=dict, required=False, default={}), 'hlo_version': FieldInfo(annotation=Union[str, NoneType], required=False, default_factory=get_hlo_version), 'orchestrator': FieldInfo(annotation=MachineModel, required=False, default=MachineModel(server_name=None, machine_name=None, hostname=None, port=None)), 'sequence_codehash': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'sequence_comment': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'sequence_label': FieldInfo(annotation=Union[str, NoneType], required=False, default='noLabel'), 'sequence_name': FieldInfo(annotation=Union[str, NoneType], required=False, default=None), 'sequence_output_dir': FieldInfo(annotation=Union[Path, NoneType], required=False, default=None), 'sequence_params': FieldInfo(annotation=Union[dict, NoneType], required=False, default={}), 'sequence_status': FieldInfo(annotation=List[HloStatus], required=False, default=[]), 'sequence_timestamp': FieldInfo(annotation=Union[datetime, NoneType], required=False, default=None), 'sequence_uuid': FieldInfo(annotation=Union[UUID, NoneType], required=False, default=None), 'simulation': FieldInfo(annotation=bool, required=False, default=False)}*

Metadata about the fields defined on the model,
mapping of field names to [FieldInfo][pydantic.fields.FieldInfo] objects.

This replaces Model._\_fields_\_ from Pydantic V1.

## helao.helpers.print_message module

### helao.helpers.print_message.print_message(server_cfg={}, server_name=None, \*args, \*\*kwargs)

Prints and logs messages with different styles based on the server configuration and message type.

Args:
: server_cfg (dict, optional): Configuration dictionary for the server. Defaults to {}.
  server_name (str, optional): Name of the server. Defaults to None.
  <br/>
  ```
  *
  ```
  <br/>
  args: Variable length argument list for the message content.
  <br/>
  ```
  **
  ```
  <br/>
  kwargs: Arbitrary keyword arguments for additional options.
  <br/>
  > - error (bool, optional): If present, the message is treated as an error.
  > - warning (bool, optional): If present, the message is treated as a warning.
  > - warn (bool, optional): Alias for warning.
  > - info (bool, optional): If present, the message is treated as an informational message.
  > - sample (bool, optional): If present, the message is treated as a sample message.
  > - log_dir (str, optional): Directory path where the log files will be saved.

Returns:
: None

## helao.helpers.rcp_to_dict module

### helao.helpers.rcp_to_dict.rcp_to_dict(rcppath)

Convert a structured text file or a file within a zip archive into a nested dictionary.

The function reads a file with a specific structure where each line contains a key-value pair
separated by a colon and indented with tabs to indicate hierarchy levels. It supports reading
from both plain text files and zip archives containing the file. The resulting dictionary
reflects the hierarchical structure of the input file.

Args:
: rcppath (str): The path to the input file. It can be a plain text file or a zip archive
  : containing the file.

Returns:
: dict: A nested dictionary representing the hierarchical structure of the input file.

## helao.helpers.read_hlo module

This module provides functionality to read and manage Helao data files, specifically .hlo files and YAML files. It includes the following:
Functions:

> read_hlo(path: str) -> Tuple[dict, dict]:

Classes:
: HelaoData:
  : \_\_init_\_(self, target: str, 
    <br/>
    ```
    **
    ```
    <br/>
    kwargs):
    ls:
    read_hlo(self, hlotarget):
    read_file(self, hlotarget):
    data:
    \_\_repr_\_(self):
    <br/>
    > Returns a string representation of the object.

### *class* helao.helpers.read_hlo.HelaoData(target, \*\*kwargs)

Bases: `object`

A class to represent and manage Helao data, which can be stored in either a directory or a zip file.

Attributes:
: ord (list): Order of data types.
  abbrd (dict): Abbreviations for data types.
  target (str): Path to the target file or directory.
  zflist (list): List of files in the zip archive.
  ymlpath (str): Path to the YAML file.
  ymldir (str): Directory containing the YAML file.
  type (str): Type of the data (sequence, experiment, or action).
  yml (dict): Parsed YAML content.
  seq (list): List of sequence data.
  exp (list): List of experiment data.
  act (list): List of action data.
  data_files (list): List of data files.
  name (str): Name of the data.
  params (dict): Parameters of the data.
  uuid (str): UUID of the data.
  timestamp (str): Timestamp of the data.
  samples_in (list): List of input samples.
  children (list): List of child data objects.

Methods:
: ls: Prints a list of child data objects.
  read_hlo(hlotarget): Reads HLO data from the target.
  read_file(hlotarget): Reads a file from the zip archive.
  data: Returns the data from the first data file.
  \_\_repr_\_(): Returns a string representation of the object.

#### \_\_init_\_(target, \*\*kwargs)

Initialize a HelaoData object.

Parameters:
target (str): The target file or directory. This can be a path to a zip file,

> a directory, or a YAML file.

```
**
```

kwargs: Additional keyword arguments.
: - zflist (list): List of files in the zip archive.
  - ztarget (str): Target YAML file within the zip archive.

Attributes:
ord (list): List of strings representing the order of data types.
abbrd (dict): Dictionary mapping abbreviations to full names.
target (str): The target file or directory.
zflist (list): List of files in the zip archive.
ymlpath (str): Path to the YAML file.
ymldir (str): Directory containing the YAML file.
type (str): Type of the YAML file (sequence, experiment, or action).
yml (dict): Parsed YAML content.
seq (list): List of HelaoData objects for sequences.
exp (list): List of HelaoData objects for experiments.
act (list): List of HelaoData objects for actions.
data_files (list): List of data files.
name (str): Name of the sequence, experiment, or action.
params (dict): Parameters of the sequence, experiment, or action.
uuid (str): UUID of the sequence, experiment, or action.
timestamp (str): Timestamp of the sequence, experiment, or action.
samples_in (list): List of input samples.
children (list): List of child HelaoData objects (sequences, experiments, actions).

#### *property* data

Reads the first data file in the data_files list using the read_hlo method.

Returns:
: The data read from the first file in the data_files list.

#### *property* ls

Prints a formatted string representation of the current object and its children.

The method prints the string representation of the current object followed by
the string representations of its children, each prefixed with their index in
the list of children.

Returns:
: None

#### read_file(hlotarget)

Reads the contents of a file within a zip archive.

Args:
: hlotarget (str): The path to the target file within the zip archive.

Returns:
: bytes: The contents of the file as bytes.

#### read_hlo(hlotarget)

Reads and processes a .hlo file from a zip archive or directly.

If the target file ends with “.zip”, it reads the specified hlotarget file
from within the zip archive, decodes the lines, and processes the metadata
and data sections. The metadata is parsed as YAML, and the data is parsed
as JSON and stored in a defaultdict.

Args:
: hlotarget (str): The target .hlo file to read.

Returns:
: tuple: A tuple containing:
  - meta (dict): The metadata parsed from the .hlo file.
  - data (defaultdict): The data parsed from the .hlo file, organized
  <br/>
  > into a defaultdict of lists.

### helao.helpers.read_hlo.read_hlo(path)

* **Return type:**
  `Tuple`[`dict`, `dict`]

Reads a .hlo file and returns its metadata and data.
Args:

> path (str): The file path to the .hlo file.

Returns:
: Tuple[dict, dict]: A tuple containing two dictionaries:
  : - The first dictionary contains the metadata.
    - The second dictionary contains the data, where each key maps to a list of values.

## helao.helpers.ref_electrode module

## helao.helpers.reference module

### *class* helao.helpers.reference.Reference

Bases: `object`

#### Vnhe *: `float`*

#### name *: `str`*

## helao.helpers.sample_api module

### *class* helao.helpers.sample_api.AssemblySampleAPI(Serv_class)

Bases: `_BaseSampleAPI`

#### \_\_init_\_(Serv_class)

### *class* helao.helpers.sample_api.GasSampleAPI(Serv_class)

Bases: `_BaseSampleAPI`

#### \_\_init_\_(Serv_class)

### *class* helao.helpers.sample_api.LiquidSampleAPI(Serv_class)

Bases: `_BaseSampleAPI`

#### \_\_init_\_(Serv_class)

#### *async* old_jsondb_to_sqlitedb()

### *class* helao.helpers.sample_api.OldLiquidSampleAPI(Serv_class)

Bases: `object`

#### \_\_init_\_(Serv_class)

#### *async* count_samples()

#### *async* get_samples(sample)

accepts a liquid sample model with minimum information to find it in the db
and returns its full information

#### *async* new_samples(new_sample)

### *class* helao.helpers.sample_api.UnifiedSampleDataAPI(Serv_class)

Bases: `object`

#### \_\_init_\_(Serv_class)

#### *async* get_platemap(samples=[])

* **Return type:**
  `None`

#### *async* get_samples(samples=[])

this will only use the sample_no for local sample, or global_label for external samples
and fills in the rest from the db and returns the list again.
We expect to not have mixed sample types here.

* **Return type:**
  `List`[`Union`[`AssemblySample`, `LiquidSample`, `GasSample`, `SolidSample`, `NoneSample`]]

#### *async* get_samples_xy(samples=[])

* **Return type:**
  `None`

#### *async* init_db()

* **Return type:**
  `None`

#### *async* list_new_samples(limit=10)

this will only use the sample_no for local sample, or global_label for external samples
and fills in the rest from the db and returns the list again.
We expect to not have mixed sample types here.

* **Return type:**
  `List`[`Union`[`AssemblySample`, `LiquidSample`, `GasSample`, `SolidSample`, `NoneSample`]]

#### *async* new_samples(samples=[])

* **Return type:**
  `List`[`Union`[`AssemblySample`, `LiquidSample`, `GasSample`, `SolidSample`, `NoneSample`]]

#### *async* update_samples(samples=[])

* **Return type:**
  `None`

## helao.helpers.sample_positions module

### *class* helao.helpers.sample_positions.Custom(\*\*data)

Bases: `BaseModel`, `HelaoDict`

#### assembly_allowed()

* **Return type:**
  `bool`

#### blocked *: `bool`*

#### custom_name *: `str`*

#### custom_type *: [`CustomTypes`](#helao.helpers.sample_positions.CustomTypes)*

#### dest_allowed()

* **Return type:**
  `bool`

#### dilution_allowed()

* **Return type:**
  `bool`

#### is_destroyed()

* **Return type:**
  `bool`

#### load(sample_in)

* **Return type:**
  `Tuple`[`bool`, `Union`[`AssemblySample`, `LiquidSample`, `GasSample`, `SolidSample`, `NoneSample`]]

#### max_vol_ml *: `Optional`[`float`]*

#### model_computed_fields *: ClassVar[Dict[str, ComputedFieldInfo]]* *= {}*

A dictionary of computed field names and their corresponding ComputedFieldInfo objects.

#### model_config *: ClassVar[ConfigDict]* *= {}*

Configuration for the model, should be a dictionary conforming to [ConfigDict][pydantic.config.ConfigDict].

#### model_fields *: ClassVar[Dict[str, FieldInfo]]* *= {'blocked': FieldInfo(annotation=bool, required=False, default=False), 'custom_name': FieldInfo(annotation=str, required=True), 'custom_type': FieldInfo(annotation=CustomTypes, required=True), 'max_vol_ml': FieldInfo(annotation=Union[float, NoneType], required=False, default=None), 'sample': FieldInfo(annotation=Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample], required=False, default=NoneSample(hlo_version='2024.04.18', global_label=None, sample_type=None, inheritance=None, status=[]))}*

Metadata about the fields defined on the model,
mapping of field names to [FieldInfo][pydantic.fields.FieldInfo] objects.

This replaces Model._\_fields_\_ from Pydantic V1.

#### sample *: `Union`[`AssemblySample`, `LiquidSample`, `GasSample`, `SolidSample`, `NoneSample`]*

#### unload()

* **Return type:**
  `Union`[`AssemblySample`, `LiquidSample`, `GasSample`, `SolidSample`, `NoneSample`]

### *class* helao.helpers.sample_positions.CustomTypes(value, names=None, \*, module=None, qualname=None, type=None, start=1, boundary=None)

Bases: `str`, `Enum`

#### cell *= 'cell'*

#### injector *= 'injector'*

#### reservoir *= 'reservoir'*

#### waste *= 'waste'*

### *class* helao.helpers.sample_positions.Positions(\*\*data)

Bases: `BaseModel`, `HelaoDict`

#### customs_dict *: `Dict`[`str`, [`Custom`](#helao.helpers.sample_positions.Custom)]*

#### model_computed_fields *: ClassVar[Dict[str, ComputedFieldInfo]]* *= {}*

A dictionary of computed field names and their corresponding ComputedFieldInfo objects.

#### model_config *: ClassVar[ConfigDict]* *= {}*

Configuration for the model, should be a dictionary conforming to [ConfigDict][pydantic.config.ConfigDict].

#### model_fields *: ClassVar[Dict[str, FieldInfo]]* *= {'customs_dict': FieldInfo(annotation=Dict[str, Custom], required=False, default={}), 'trays_dict': FieldInfo(annotation=Dict[int, Dict[int, Union[VT15, VT54, VT70, NoneType]]], required=False, default={})}*

Metadata about the fields defined on the model,
mapping of field names to [FieldInfo][pydantic.fields.FieldInfo] objects.

This replaces Model._\_fields_\_ from Pydantic V1.

#### trays_dict *: `Dict`[`int`, `Dict`[`int`, `Optional`[VTUnion]]]*

### *class* helao.helpers.sample_positions.VT15(\*\*data)

Bases: `_VT_template`

#### VTtype *: `Literal`[`'VT15'`]*

#### max_vol_ml *: `Literal`[`10`]*

#### model_computed_fields *: ClassVar[Dict[str, ComputedFieldInfo]]* *= {}*

A dictionary of computed field names and their corresponding ComputedFieldInfo objects.

#### model_config *: ClassVar[ConfigDict]* *= {}*

Configuration for the model, should be a dictionary conforming to [ConfigDict][pydantic.config.ConfigDict].

#### model_fields *: ClassVar[Dict[str, FieldInfo]]* *= {'VTtype': FieldInfo(annotation=Literal['VT15'], required=False, default='VT15'), 'blocked': FieldInfo(annotation=List[bool], required=False, default=[]), 'max_vol_ml': FieldInfo(annotation=Literal[10], required=False, default=10.0), 'positions': FieldInfo(annotation=Literal[15], required=False, default=15), 'samples': FieldInfo(annotation=List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]], required=False, default=[]), 'vials': FieldInfo(annotation=List[bool], required=False, default=[])}*

Metadata about the fields defined on the model,
mapping of field names to [FieldInfo][pydantic.fields.FieldInfo] objects.

This replaces Model._\_fields_\_ from Pydantic V1.

#### positions *: `Literal`[`15`]*

### *class* helao.helpers.sample_positions.VT54(\*\*data)

Bases: `_VT_template`

#### VTtype *: `Literal`[`'VT54'`]*

#### max_vol_ml *: `Literal`[`2`]*

#### model_computed_fields *: ClassVar[Dict[str, ComputedFieldInfo]]* *= {}*

A dictionary of computed field names and their corresponding ComputedFieldInfo objects.

#### model_config *: ClassVar[ConfigDict]* *= {}*

Configuration for the model, should be a dictionary conforming to [ConfigDict][pydantic.config.ConfigDict].

#### model_fields *: ClassVar[Dict[str, FieldInfo]]* *= {'VTtype': FieldInfo(annotation=Literal['VT54'], required=False, default='VT54'), 'blocked': FieldInfo(annotation=List[bool], required=False, default=[]), 'max_vol_ml': FieldInfo(annotation=Literal[2], required=False, default=2.0), 'positions': FieldInfo(annotation=Literal[54], required=False, default=54), 'samples': FieldInfo(annotation=List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]], required=False, default=[]), 'vials': FieldInfo(annotation=List[bool], required=False, default=[])}*

Metadata about the fields defined on the model,
mapping of field names to [FieldInfo][pydantic.fields.FieldInfo] objects.

This replaces Model._\_fields_\_ from Pydantic V1.

#### positions *: `Literal`[`54`]*

### *class* helao.helpers.sample_positions.VT70(\*\*data)

Bases: `_VT_template`

#### VTtype *: `Literal`[`'VT70'`]*

#### max_vol_ml *: `Literal`[`1`]*

#### model_computed_fields *: ClassVar[Dict[str, ComputedFieldInfo]]* *= {}*

A dictionary of computed field names and their corresponding ComputedFieldInfo objects.

#### model_config *: ClassVar[ConfigDict]* *= {}*

Configuration for the model, should be a dictionary conforming to [ConfigDict][pydantic.config.ConfigDict].

#### model_fields *: ClassVar[Dict[str, FieldInfo]]* *= {'VTtype': FieldInfo(annotation=Literal['VT70'], required=False, default='VT70'), 'blocked': FieldInfo(annotation=List[bool], required=False, default=[]), 'max_vol_ml': FieldInfo(annotation=Literal[1], required=False, default=1.0), 'positions': FieldInfo(annotation=Literal[70], required=False, default=70), 'samples': FieldInfo(annotation=List[Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]], required=False, default=[]), 'vials': FieldInfo(annotation=List[bool], required=False, default=[])}*

Metadata about the fields defined on the model,
mapping of field names to [FieldInfo][pydantic.fields.FieldInfo] objects.

This replaces Model._\_fields_\_ from Pydantic V1.

#### positions *: `Literal`[`70`]*

## helao.helpers.sequence_constructor module

### helao.helpers.sequence_constructor.constructor(sequence_function, params={}, sequence_label=None, data_request_id=None)

Constructs a Sequence object by invoking a sequence function with specified parameters.

* **Return type:**
  [`Sequence`](#helao.helpers.premodels.Sequence)

Args:
: sequence_function (callable): The function that generates the sequence of experiments.
  params (dict, optional): A dictionary of parameters to pass to the sequence function. Defaults to {}.
  sequence_label (str, optional): An optional label for the sequence. Defaults to None.
  data_request_id (UUID, optional): An optional UUID for data request identification. Defaults to None.

Returns:
: Sequence: A Sequence object containing the generated sequence of experiments.

## helao.helpers.server_api module

### *class* helao.helpers.server_api.HelaoBokehAPI(helao_cfg, helao_srv, doc)

Bases: `object`

A class to represent the Helao Bokeh API.

### Attributes:

helao_cfg
: Configuration dictionary for Helao.

helao_srv
: Name of the Helao server.

doc
: Bokeh document object.

### Methods:

\_\_init_\_(self, helao_cfg: dict, helao_srv: str, doc):
: Initializes the HelaoBokehAPI with the given configuration, server name, and Bokeh document.

#### \_\_init_\_(helao_cfg, helao_srv, doc)

### *class* helao.helpers.server_api.HelaoFastAPI(helao_cfg, helao_srv, \*args, \*\*kwargs)

Bases: `FastAPI`

HelaoFastAPI is a subclass of FastAPI that initializes with specific configuration
parameters for the Helao server.

Attributes:
: helao_cfg (dict): Configuration dictionary for Helao.
  helao_srv (str): Name of the Helao server.
  server_cfg (dict): Configuration dictionary for the specific server.
  server_params (dict): Additional parameters for the server.

Methods:
: \_\_init_\_(helao_cfg: dict, helao_srv: str, 
  <br/>
  ```
  *
  ```
  <br/>
  args, 
  <br/>
  ```
  **
  ```
  <br/>
  kwargs):
  : Initializes the HelaoFastAPI instance with the given configuration and server name.

#### \_\_init_\_(helao_cfg, helao_srv, \*args, \*\*kwargs)

Initializes the server API with the given configuration.

Args:
: helao_cfg (dict): Configuration dictionary for helao.
  helao_srv (str): Server name.
  <br/>
  ```
  *
  ```
  <br/>
  args: Variable length argument list.
  <br/>
  ```
  **
  ```
  <br/>
  kwargs: Arbitrary keyword arguments.

Attributes:
: helao_cfg (dict): Stores the helao configuration.
  helao_srv (str): Stores the server name.
  server_cfg (dict): Configuration for the specific server.
  server_params (dict): Parameters for the server configuration.

## helao.helpers.set_time module

### helao.helpers.set_time.set_time(offset=0)

## helao.helpers.spec_map module

## helao.helpers.specification_parser module

### *class* helao.helpers.specification_parser.BaseParser

Bases: `object`

#### \_\_init_\_()

#### list_params(specfile, orch)

#### lister(folderpath, limit=50)

#### parser(orch, params={}, \*\*kwargs)

## helao.helpers.to_json module

### helao.helpers.to_json.parse_bokeh_input(v)

Parses a given input string, attempting to convert it from a JSON-like format
with single quotes to a proper JSON format with double quotes. If the conversion
fails, the original input is returned. The resulting value is then processed to
fix any numeric types.

Args:
: v (str): The input string to be parsed.

Returns:
: Any: The parsed and processed value, which could be of any type depending on
  the input and the result of the numeric fixing process.

## helao.helpers.unpack_samples module

### helao.helpers.unpack_samples.unpack_samples_helper(samples=[])

Unpacks a list of samples into separate lists based on their sample type.

This function takes a list of samples, which can include nested assembly samples,
and recursively unpacks them into separate lists for liquid, solid, and gas samples.

* **Return type:**
  `Tuple`[`List`[`Union`[`AssemblySample`, `LiquidSample`, `GasSample`, `SolidSample`, `NoneSample`]], `List`[`Union`[`AssemblySample`, `LiquidSample`, `GasSample`, `SolidSample`, `NoneSample`]]]

Args:
: samples (List[SampleUnion]): A list of samples to be unpacked. Each sample can be of type
  : liquid, solid, gas, or assembly. Assembly samples can contain
    other samples, including nested assemblies.

Returns:
: Tuple[List[SampleUnion], List[SampleUnion], List[SampleUnion]]: A tuple containing three lists:
  : - liquid_list: List of liquid samples.
    - solid_list: List of solid samples.
    - gas_list: List of gas samples.

## helao.helpers.update_sample_vol module

### helao.helpers.update_sample_vol.update_vol(BS, delta_vol_ml, dilute)

Updates the volume of a sample and optionally adjusts its dilution factor.

Parameters:
BS (_BaseSample): The sample object which contains volume and dilution factor attributes.
delta_vol_ml (float): The change in volume to be applied to the sample, in milliliters.
dilute (bool): A flag indicating whether to adjust the dilution factor based on the new volume.

Behavior:
- If the sample has a ‘volume_ml’ attribute, the volume is updated by adding ‘delta_vol_ml’.
- If the resulting total volume is less than or equal to zero, the volume is set to zero and the sample status is set to destroyed.
- If ‘dilute’ is True and the sample has a ‘dilution_factor’ attribute, the dilution factor is recalculated based on the new volume.
- Appropriate messages are printed to indicate changes and errors.

Notes:
- If the previous volume is less than or equal to zero, the new dilution factor is set to -1.

## helao.helpers.ws_publisher module

### *class* helao.helpers.ws_publisher.WsPublisher(source_queue, xform_func=<function WsPublisher.<lambda>>)

Bases: `object`

WsPublisher is a class that manages WebSocket connections and broadcasts messages from a source queue to all active connections.

Attributes:
: active_connections (List[WebSocket]): A list of currently active WebSocket connections.
  source_queue: The queue from which messages are sourced.
  xform_func (function): A transformation function applied to each message before broadcasting.

Methods:
: \_\_init_\_(source_queue, xform_func=lambda x: x):
  : Initializes the WsPublisher with a source queue and an optional transformation function.
  <br/>
  connect(websocket: WebSocket):
  : Accepts a WebSocket connection and adds it to the list of active connections.
  <br/>
  disconnect(websocket: WebSocket):
  : Removes a WebSocket connection from the list of active connections.
  <br/>
  broadcast(websocket: WebSocket):
  : Subscribes to the source queue and broadcasts transformed messages to the WebSocket connection.

#### \_\_init_\_(source_queue, xform_func=<function WsPublisher.<lambda>>)

Initializes the WsPublisher instance.

Args:
: source_queue (queue.Queue): The source queue from which messages will be consumed.
  xform_func (callable, optional): A transformation function to apply to each message.
  <br/>
  > Defaults to a no-op function (lambda x: x).

Attributes:
: active_connections (list): A list to keep track of active connections.
  source_queue (queue.Queue): The source queue from which messages will be consumed.
  xform_func (callable): A transformation function to apply to each message.

#### active_connections *: `List`[`WebSocket`]*

#### *async* broadcast(websocket)

Broadcasts messages from the source queue to the given websocket.

This method subscribes to the source queue and listens for messages.
Each message is transformed using the xform_func and then compressed
using pyzstd before being sent to the websocket.

Args:
: websocket (WebSocket): The websocket to which messages are broadcasted.

Raises:
: websockets.ConnectionClosedError: If the client closes the connection
  : without sending a close frame.

#### *async* connect(websocket)

Handles a new WebSocket connection.

This method accepts an incoming WebSocket connection and adds it to the list of active connections.

Args:
: websocket (WebSocket): The WebSocket connection to be accepted and added to active connections.

Returns:
: None

#### disconnect(websocket)

Disconnects a WebSocket connection.

This method removes the given WebSocket connection from the list of active connections.

Args:
: websocket (WebSocket): The WebSocket connection to be removed from active connections.

## helao.helpers.ws_subscriber module

A module for WebSocket clients, both synchronous and asynchronous, to read and process messages from a WebSocket server.
Classes:

> WsSyncClient:
> : A synchronous WebSocket client for reading messages from a specified server.
>   : \_\_init_\_(host, port, path):

> WsSubscriber:
> : A class that subscribes to a WebSocket server and receives broadcasted messages asynchronously.
>   : Initializes the WebSocket subscriber with the given host, port, path, and optional max queue length.

### *class* helao.helpers.ws_subscriber.WsSubscriber(host, port, path, max_qlen=500)

Bases: `object`

WsSubscriber is a class that subscribes to a WebSocket server and receives broadcasted messages.

Attributes:
: data_url (str): The WebSocket URL constructed from the host, port, and path.
  recv_queue (collections.deque): A deque to store received messages with a maximum length.
  subscriber_task (asyncio.Task): An asyncio task that runs the subscriber loop.

Methods:
: \_\_init_\_(host, port, path, max_qlen=500):
  : Initializes the WsSubscriber with the given host, port, path, and optional max queue length.
  <br/>
  subscriber_loop():
  : Coroutine that connects to the WebSocket server and receives messages, retrying on failure.
  <br/>
  read_messages():
  : Asynchronously empties the recv_queue and returns the messages.

#### \_\_init_\_(host, port, path, max_qlen=500)

Initializes the WebSocket subscriber.

Args:
: host (str): The hostname or IP address of the WebSocket server.
  port (int): The port number of the WebSocket server.
  path (str): The path to the WebSocket endpoint.
  max_qlen (int, optional): The maximum length of the receive queue. Defaults to 500.

#### *async* read_messages()

Asynchronously reads messages from the receive queue.

This method continuously reads messages from the recv_queue until it is empty.
Each message is appended to a list which is returned at the end.

Returns:
: list: A list of messages read from the recv_queue.

#### *async* subscriber_loop()

Asynchronous method to handle the subscription loop for receiving data.

This method attempts to connect to a WebSocket server at self.data_url and 
receive data in a loop. The received data is expected to be compressed with 
pyzstd and serialized with pickle. The decompressed and deserialized data 
is appended to self.recv_queue.

If the connection fails, it will retry up to retry_limit times with a delay 
of 2 seconds between each retry.

Attributes:
: retry_limit (int): The number of times to retry the connection before giving up.
  retry_idx (int): The current retry attempt index.
  recv_bytes (bytes): The raw bytes received from the WebSocket.
  recv_data_dict (dict): The decompressed and deserialized data received from the WebSocket.

Raises:
: Exception: If an error occurs during the connection or data reception process.

### *class* helao.helpers.ws_subscriber.WsSyncClient(host, port, path)

Bases: `object`

A WebSocket synchronous client for reading messages from a specified server.

Attributes:
: data_url (str): The WebSocket URL constructed from the host, port, and path.

Methods:
: read_messages():
  : Reads messages from the WebSocket server. Retries up to a specified limit
    if the connection fails. Returns the decompressed and deserialized message
    if successful, otherwise returns an empty dictionary.

#### \_\_init_\_(host, port, path)

Initializes the WebSocket subscriber with the given host, port, and path.

Args:
: host (str): The hostname or IP address of the WebSocket server.
  port (int): The port number of the WebSocket server.
  path (str): The path to the WebSocket endpoint.

Attributes:
: data_url (str): The constructed WebSocket URL.

#### read_messages()

Attempts to read and decompress messages from a WebSocket connection.

This method tries to establish a connection to the WebSocket server
specified by self.data_url and read messages from it. The messages
are expected to be compressed using pyzstd and serialized using
pickle. If the connection or reading fails, it will retry up to
retry_limit times with a delay between retries.

Returns:
: dict: The decompressed and deserialized message if successful,
  : otherwise an empty dictionary.

Raises:
: Exception: If an error occurs during connection or message reading.

## helao.helpers.yml_finisher module

### *async* helao.helpers.yml_finisher.yml_finisher(yml_path, db_config={}, retry=3)

Asynchronously attempts to finish processing a YAML file by sending a request to a specified database server.

Args:
: yml_path (str): The file path to the YAML file.
  db_config (dict, optional): A dictionary containing the database configuration with keys “host” and “port”. Defaults to an empty dictionary.
  retry (int, optional): The number of retry attempts if the request fails. Defaults to 3.

Returns:
: bool: True if the YAML file was successfully processed, False otherwise.

## helao.helpers.yml_tools module

### helao.helpers.yml_tools.yml_dumps(obj, options=None)

Serializes a Python object to a YAML-formatted string.

Args:
: obj (Any): The Python object to serialize.
  options (dict, optional): Additional options to pass to the YAML dumper. Defaults to None.

Returns:
: str: The YAML-formatted string representation of the input object.

Note:
: - The YAML dumper is configured to indent mappings by 2 spaces, sequences by 4 spaces, and offset by 2 spaces.
  - Duplicate keys are allowed in the YAML output.
  - None values are represented as “null” in the YAML output.

### helao.helpers.yml_tools.yml_load(input)

Load a YAML file or string.

This function loads a YAML file or string using the ruamel.yaml library.
It supports loading from a file path, a Path object, or a YAML string.

Args:
: input (Union[str, Path]): The input YAML data. This can be a file path (str),
  : a Path object, or a YAML string.

Returns:
: obj: The loaded YAML data as a Python object.

Raises:
: FileNotFoundError: If the input is a file path that does not exist.
  ruamel.yaml.YAMLError: If there is an error parsing the YAML data.

## helao.helpers.zdeque module

### *class* helao.helpers.zdeque.zdeque(\*args, \*\*kwargs)

Bases: `deque`

A subclass of collections.deque that compresses and decompresses items using pyzstd and pickle.

Methods:
: \_\_init_\_(
  <br/>
  ```
  *
  ```
  <br/>
  args, 
  <br/>
  ```
  **
  ```
  <br/>
  kwargs):
  : Initialize the zdeque object.
  <br/>
  \_\_getitem_\_(i):
  : Retrieve the item at index i after decompressing and unpickling it.
  <br/>
  \_\_iter_\_():
  : Iterate over the items, decompressing and unpickling each one.
  <br/>
  popleft():
  : Remove and return the leftmost item after decompressing and unpickling it.
  <br/>
  pop():
  : Remove and return the rightmost item after decompressing and unpickling it.
  <br/>
  insert(i, x):
  : Insert item x at index i after pickling and compressing it.
  <br/>
  append(x):
  : Append item x to the right end after pickling and compressing it.
  <br/>
  appendleft(x):
  : Append item x to the left end after pickling and compressing it.
  <br/>
  index(x):
  : Return the index of item x after pickling and compressing it.

#### \_\_init_\_(\*args, \*\*kwargs)

Initialize a new instance of the class.

Parameters:

```
*
```

args: Variable length argument list.

```
**
```

kwargs: Arbitrary keyword arguments.

#### append(x)

Append an item to the deque after compressing and serializing it.

Args:
: x: The item to be appended to the deque. It will be serialized using
  : pickle and then compressed using pyzstd before being appended.

#### appendleft(x)

Add an element to the left end of the deque after compressing and serializing it.

Args:
: x: The element to be added to the left end of the deque. The element will be
  : serialized using pickle and then compressed using pyzstd before being added.

#### index(x)

Returns the index of the first occurrence of the specified element in the deque.

Args:
: x: The element to search for in the deque. The element will be serialized
  : using pickle and compressed using pyzstd before searching.

Returns:
: int: The index of the first occurrence of the specified element.

Raises:
: ValueError: If the element is not present in the deque.

#### insert(i, x)

Inserts an element at a given position in the deque.

Args:
: i (int): The index at which the element should be inserted.
  x (Any): The element to be inserted. It will be serialized and compressed before insertion.

Returns:
: None

#### pop()

Remove and return an object from the deque.

This method overrides the default pop method to decompress and 
deserialize the object using pyzstd and pickle before returning it.

Returns:
: Any: The decompressed and deserialized object from the deque.

#### popleft()

Remove and return an object from the left end of the deque.

This method overrides the popleft method of the superclass to 
decompress and deserialize the object using pyzstd and pickle.

Returns:
: Any: The decompressed and deserialized object from the left end of the deque.

## helao.helpers.zeroconf_manager module

Zeroconf service broadcast class used by HELAO servers

Service properties will include instrument tag and a broader group tag. The group tag
will designate service resources that may be shared across instruments.

### *class* helao.helpers.zeroconf_manager.ZeroconfManager(server_name, server_host, server_port)

Bases: `object`

#### \_\_init_\_(server_name, server_host, server_port)

#### disable()

#### enable()

#### *async* register_services(infos)

* **Return type:**
  `None`

#### *async* unregister_services(infos)

* **Return type:**
  `None`

## helao.helpers.zip_dir module

### helao.helpers.zip_dir.rm_tree(pth)

Recursively removes a directory and all its contents.

Args:
: pth (str or Path): The path to the directory to be removed.

Raises:
: FileNotFoundError: If the directory does not exist.
  PermissionError: If the user does not have permission to delete a file or directory.
  OSError: If an error occurs while deleting a file or directory.

### helao.helpers.zip_dir.zip_dir(dir, filename)

Compresses the contents of a directory into a zip file.

Args:
: dir (Union[Path, str]): The directory to compress. Can be a Path object or a string.
  filename (Union[Path, str]): The name of the output zip file. Can be a Path object or a string.

Returns:
: None

Raises:
: Exception: If an error occurs during the zipping process, an exception is caught and its traceback is printed.

Notes:
: - Files with the “.lock” suffix are excluded from the zip file.
  - If the zipping process is successful, the original directory is removed using the rm_tree function.

## helao.helpers.zmq_manager module

ZeroMQ PUB/SUB and REQ/REP class used by HELAO servers

ZeroMQ will succeed REST HTTP and websocket status/data broadcasting and subscriptions.

## helao.helpers.zstd_io module

### helao.helpers.zstd_io.unzpickle(fpath)

Uncompresses a zstd compressed file and deserializes the contained pickle object.

Args:
: fpath (str): The file path to the zstd compressed file.

Returns:
: object: The deserialized object from the pickle file.

### helao.helpers.zstd_io.zpickle(fpath, data)

Serializes the given data and writes it to a file using Zstandard compression.

Args:
: fpath (str): The file path where the compressed data will be written.
  data (Any): The data to be serialized and compressed.

Returns:
: bool: True if the operation is successful.

Raises:
: Exception: If there is an error during the file writing process.

Example:
: zpickle(‘data.zst’, my_data)

## Module contents
