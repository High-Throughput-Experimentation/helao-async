import os
import json
from glob import glob
from uuid import UUID
from datetime import datetime
from zipfile import ZipFile
from collections import defaultdict
from typing import Optional

import pandas as pd

from helao.helpers.yml_tools import yml_load
from helao.helpers.file_mapper import FileMapper


class LocalLoader:
    """Provides cached access to local data.
    The LocalLoader class is designed to efficiently load and manage data
    from a local file system, including data stored in zip archives. It
    maintains separate caches for actions, experiments, sequences, and
    processes to minimize redundant file reads. It also provides methods
    to retrieve metadata and hierarchical lab object (HLO) data associated
    with these entities.
    The class supports loading data from various directory structures,
    including those used to organize experiment runs in different states
    (e.g., active, finished, synced, diagnostic). It can handle both
    individual YAML files and YAML files stored within zip archives.
    Attributes:
        act_cache (dict): A cache for action metadata, keyed by file path.
        exp_cache (dict): A cache for experiment metadata, keyed by file path.
        seq_cache (dict): A cache for sequence metadata, keyed by file path.
        prc_cache (dict): A cache for process metadata, keyed by file path.
        target (str): The base directory or zip file path being managed.
        sequences (pd.DataFrame): A DataFrame containing sequence metadata.
        experiments (pd.DataFrame): A DataFrame containing experiment metadata.
        actions (pd.DataFrame): A DataFrame containing action metadata.
        processes (pd.DataFrame): A DataFrame containing process metadata.
    Methods:
        __init__(data_path: str): Initializes the LocalLoader with a data path.
        clear_cache(): Clears all data caches.
        get_yml(path: str): Loads and returns YAML data from the specified path.
        get_act(index: int = None, path: str = None): Retrieves an action by index or path.
        get_exp(index: int = None, path: str = None): Retrieves an experiment by index or path.
        get_seq(index: int = None, path: str = None): Retrieves a sequence by index or path.
        get_prc(index: int = None, path: str = None): Retrieves a process by index or path.
        get_hlo(yml_path: str, hlo_fn: str): Retrieves hierarchical lab object (HLO) data.
    """

    def __init__(self, data_path: str):
        self.act_cache = {}  # {uuid: json_dict}
        self.exp_cache = {}
        self.seq_cache = {}
        self.prc_cache = {}
        self._yml_paths = {}
        self.target = os.path.abspath(os.path.normpath(data_path.strip('"').strip("'")))
        target_state = self.target.split("RUNS_")[-1].split(os.sep)[0]
        states = ("RUNS_ACTIVE", "RUNS_FINISHED", "RUNS_SYNCED", "RUNS_DIAG")
        state_dir = f"RUNS_{target_state}"
        if self.target.endswith(".zip"):
            process_dir = self.target.replace(state_dir, "PROCESSES").replace(".zip", "")
        else:
            process_dir = os.path.dirname(self.target).replace(state_dir, "PROCESSES") 
        check_dirs = [
            f"{self.target.replace(state_dir, x)}" for x in states
        ] + [process_dir]
        if not os.path.exists(self.target):
            raise FileNotFoundError(
                "data_path argument is not a valid file or folder path"
            )
        _yml_paths = []
        if self.target.endswith(".zip"):
            with ZipFile(self.target, "r") as zf:
                zip_contents = zf.namelist()
            _yml_paths = [x for x in zip_contents if x.endswith(".yml")]
            _yml_paths += glob(os.path.join(process_dir, "**", "*-prc.yml"), recursive=True)
        elif os.path.isdir(self.target):
            for check_dir in check_dirs:
                _yml_paths += glob(os.path.join(check_dir, "**", "*.yml"), recursive=True)
        else:
            for check_dir in check_dirs:
                _yml_paths += glob(
                    os.path.join(os.path.dirname(check_dir), "**", "*.yml"),
                    recursive=True,
                )

        for suffix in ("seq", "exp", "act", "prc"):
            self._yml_paths[suffix] = [
                x for x in _yml_paths if x.endswith(f"-{suffix}.yml")
            ]

        seq_parts = []
        for ymlp in self._yml_paths["seq"]:
            yml_dir = os.path.basename(os.path.dirname(ymlp))
            if self.target.endswith(".zip"):
                yml_dir = os.path.basename(self.target).replace(".zip", "")
            _, seq_name, seq_lab = yml_dir.split("__")
            plate_id = -1
            check_serial = seq_lab.split("-")[-1]
            if check_serial.isdigit() and len(check_serial) > 1:
                plate_str = check_serial[:-1]
                checksum = check_serial[-1]
                if sum([int(x) for x in plate_str]) % 10 == int(checksum):
                    plate_id = int(plate_str)
                    seq_lab = seq_lab.split("-")[0]
            yml_file = os.path.basename(ymlp)
            timestamp = datetime.strptime(yml_file.split("-")[0], "%Y%m%d.%H%M%S%f")
            seq_parts.append((timestamp, seq_name, seq_lab, plate_id, yml_dir, ymlp))
        self.sequences = pd.DataFrame(
            seq_parts,
            columns=[
                "sequence_timestamp",
                "sequence_name",
                "sequence_label",
                "plate_id",
                "sequence_dir",
                "sequence_localpath",
            ],
        )

        exp_parts = []
        for ymlp in self._yml_paths["exp"]:
            yml_dir = os.path.basename(os.path.dirname(ymlp))
            _, exp_name = yml_dir.split("__")
            yml_file = os.path.basename(ymlp)
            timestamp = datetime.strptime(yml_file.split("-")[0], "%Y%m%d.%H%M%S%f")
            exp_parts.append(
                (
                    timestamp,
                    exp_name,
                    yml_dir,
                    ymlp,
                )
            )
        self.experiments = pd.DataFrame(
            exp_parts,
            columns=[
                "experiment_timestamp",
                "experiment_name",
                "experiment_dir",
                "experiment_localpath",
            ],
        )

        act_parts = []
        for ymlp in self._yml_paths["act"]:
            yml_dir = os.path.basename(os.path.dirname(ymlp))
            path_parts = yml_dir.split("__")
            if len(path_parts) == 5:
                act_order, act_split, _, server_name, act_name = path_parts
            elif len(path_parts) == 4:
                act_order, act_split, server_name, act_name = path_parts
            else:
                raise ValueError(f"could not parse action path parts: {path_parts}")
            yml_file = os.path.basename(ymlp)
            timestamp = datetime.strptime(yml_file.split("-")[0], "%Y%m%d.%H%M%S%f")
            act_parts.append(
                (
                    timestamp,
                    act_order,
                    act_split,
                    server_name,
                    act_name,
                    yml_dir,
                    ymlp,
                )
            )
        self.actions = pd.DataFrame(
            act_parts,
            columns=[
                "action_timestamp",
                "action_order",
                "action_split",
                "action_server",
                "action_name",
                "action_dir",
                "action_localpath",
            ],
        )
    
        prc_parts = []
        for ymlp in self._yml_paths["prc"]:
            yml_dir = os.path.basename(os.path.dirname(ymlp))
            _, exp_name = yml_dir.split("__")
            yml_file = os.path.basename(ymlp)
            idx, prc_uuid, techname = yml_file.replace("-prc.yml", "").split("__")
            prc_uuid = UUID(prc_uuid)
            prc_idx = int(idx)
            exp_timestamp = datetime.strptime(yml_dir.split("__")[0], "%Y%m%d.%H%M%S%f")
            prc_parts.append(
                (
                    prc_idx,
                    prc_uuid,
                    techname,
                    yml_dir,
                    ymlp,
                    exp_timestamp,
                    exp_name,
                )
            )
        self.processes = pd.DataFrame(
            prc_parts,
            columns=[
                "process_group_index",
                "process_uuid",
                "technique_name",
                "process_dir",
                "process_localpath",
                "experiment_timestamp",
                "experiment_name",
            ],
        )


    def clear_cache(self):
        """Clears all caches.

            This includes the action cache, experiment cache, sequence cache, and process cache.
            """
        self.act_cache = {}  # {uuid: json_dict}
        self.exp_cache = {}
        self.seq_cache = {}
        self.prc_cache = {}

    def get_yml(self, path: str):
        """Load a yml file from a given path.

            Args:
                path (str): path to the yml file

            Returns:
                dict: dictionary containing the yml data
            """
        if self.target.endswith(".zip") and not path.endswith("-prc.yml"):
            with ZipFile(self.target, "r") as zf:
                metad = dict(yml_load(zf.open(path).read().replace(b'\x89', b'%').decode("utf-8")))
        else:
            # metad = yml_load("".join(builtins.open(path, "r").readlines()))
            FM = FileMapper(path)
            metad = FM.read_yml(path)
        return metad

    def get_act(self, index=None, path: Optional[str] = None):
        """Load an action from the local filesystem.

            Args:
                index (int, optional): Index of the action in the actions dataframe. Defaults to None.
                path (str, optional): Path to the action yaml file. Defaults to None.

            Raises:
                IndexError: If neither index nor path are supplied.

            Returns:
                HelaoAction: The loaded action.
            """
        if index is None and path is None:
            raise IndexError("neither index, nor path arguments were supplied")
        if path is None:
            path = self.actions.iloc[index].action_localpath
        metad = self.act_cache.get(path, self.get_yml(path))
        self.act_cache[path] = metad
        return HelaoAction(path, metad, self)

    def get_exp(self, index=None, path: Optional[str] = None):
        """Load a single experiment from the local filesystem.

            Args:
                index (int, optional): Index of the experiment in the experiments dataframe. Defaults to None.
                path (str, optional): Path to the experiment directory. Defaults to None.

            Raises:
                IndexError: If neither index nor path are provided.

            Returns:
                HelaoExperiment: A HelaoExperiment object representing the experiment.
            """
        if index is None and path is None:
            raise IndexError("neither index, nor path arguments were supplied")
        if path is None:
            path = self.experiments.iloc[index].experiment_localpath
        metad = self.exp_cache.get(path, self.get_yml(path))
        self.exp_cache[path] = metad
        return HelaoExperiment(path, metad, self)

    def get_seq(self, index=None, path: Optional[str] = None):
        """Return a HelaoSequence object.

            Args:
                index (int, optional): Index of the sequence in the sequences dataframe. Defaults to None.
                path (str, optional): Path to the sequence directory. Defaults to None.

            Raises:
                IndexError: If neither index nor path is provided.

            Returns:
                HelaoSequence: A HelaoSequence object representing the sequence.
            """
        if index is None and path is None:
            raise IndexError("neither index, nor path arguments were supplied")
        if path is None:
            path = self.sequences.iloc[index].sequence_localpath
        metad = self.seq_cache.get(path, self.get_yml(path))
        self.seq_cache[path] = metad
        return HelaoSequence(path, metad, self)

    def get_prc(self, index=None, path: Optional[str] = None):
        """Return a HelaoProcess object from a given index or path.

            Args:
                index (int, optional): Index of the process in the processes dataframe. Defaults to None.
                path (str, optional): Path to the process yaml file. Defaults to None.

            Raises:
                IndexError: If neither index nor path is supplied.

            Returns:
                HelaoProcess: A HelaoProcess object.
            """
        if index is None and path is None:
            raise IndexError("neither index, nor path arguments were supplied")
        if path is None:
            path = self.processes.iloc[index].process_localpath
        metad = self.prc_cache.get(path, self.get_yml(path))
        self.prc_cache[path] = metad
        return HelaoProcess(path, metad, self)

    def get_hlo(self, yml_path: str, hlo_fn: str):
        """Load a HLO file, either from a zip archive or a regular file.

        Args:
            yml_path (str): The path to the YAML file associated with the HLO file.  Used to derive the HLO file's location.
            hlo_fn (str): The filename of the HLO file.

        Returns:
            Tuple[dict, dict]: A tuple containing the metadata and data from the HLO file.
                               The metadata is a dictionary loaded from the YAML header in the HLO file.
                               The data is a dictionary where keys are data series names and values are lists of data points.
                               Returns the output of FileMapper.read_hlo if the target is not a zip file.
        """
        if self.target.endswith(".zip"):
            hlotarget ="/".join([os.path.dirname(yml_path), hlo_fn])
            with ZipFile(self.target, "r") as zf:
                lines = zf.open(hlotarget).readlines()

            lines = [x.decode("UTF-8").replace("\r\n", "\n") for x in lines]
            sep_index = lines.index("%%\n")
            meta = yml_load("".join(lines[:sep_index]))

            data = defaultdict(list)
            for line in lines[sep_index + 1 :]:
                line_dict = json.loads(line)
                # print(line_dict)
                for k, v in line_dict.items():
                    if isinstance(v, list):
                        data[k] += v
                    else:
                        data[k].append(v)
            return meta, data
        else:
            # return read_hlo(os.path.join(os.path.dirname(yml_path), hlo_fn))
            FM = FileMapper(yml_path)
            hlo_path = os.path.join(os.path.dirname(yml_path), hlo_fn)
            return FM.read_hlo(hlo_path)


ABBR_MAP = {"act": "action", "exp": "experiment", "seq": "sequence", "prc": "process"}


class HelaoModel:
    """
    A base class for representing data models loaded from local YAML files.

        Attributes:
            name (str): The name of the data model.
            uuid (UUID): The unique identifier of the data model.
            helao_type (str): The type of the data model, e.g., 'sample', 'measurement', or 'process'.
            timestamp (datetime): The timestamp indicating when the data model was created.
            params (dict): A dictionary containing parameters associated with the data model.
            yml_path (str): The path to the YAML file from which the data model was loaded.
            meta_dict (dict): The raw dictionary loaded from the YAML file.
            loader (LocalLoader): The loader instance used to load the data model.

        Args:
            yml_path (str): The path to the YAML file.
            meta_dict (dict): A dictionary containing the metadata loaded from the YAML file.
            loader (LocalLoader): The LocalLoader instance used to load the data.
    """
    name: str
    uuid: UUID
    helao_type: str
    timestamp: datetime
    params: dict

    def __init__(self, yml_path: str, meta_dict: dict, loader: LocalLoader):
        yml_type = yml_path.split("-")[-1].split(".")[0]
        helao_type = ABBR_MAP[yml_type]
        self.yml_path = yml_path
        self.helao_type = helao_type
        if helao_type != "process":
            self.name = meta_dict[f"{helao_type}_name"]
        else:
            self.name = meta_dict["technique_name"]
        self.uuid = meta_dict[f"{helao_type}_uuid"]
        self.timestamp = meta_dict[f"{helao_type}_timestamp"]
        self.params = meta_dict[f"{helao_type}_params"]
        self.meta_dict = meta_dict
        self.loader = loader

    @property
    def json(self):
        return self.meta_dict


class HelaoAction(HelaoModel):
    """
    Represents a Helao action, encapsulating its metadata, parameters,
    and associated .hlo data.

    Attributes:
        action_name (str): The name of the action.
        action_uuid (UUID): The unique identifier of the action.
        action_timestamp (datetime): The timestamp of when the action was performed.
        action_params (dict): A dictionary containing the parameters of the action.

        yml_path (str): The path to the YAML file associated with the action.
        meta_dict (dict): A dictionary containing metadata associated with the action.
        loader (LocalLoader): The loader used to retrieve data associated with the action.
    """
    action_name: str
    action_uuid: UUID
    action_timestamp: datetime
    action_params: dict

    def __init__(self, yml_path: str, meta_dict: dict, loader: LocalLoader):
        super().__init__(yml_path=yml_path, meta_dict=meta_dict, loader=loader)
        self.action_name = self.name
        self.action_uuid = self.uuid
        self.action_timestamp = self.timestamp
        self.action_params = self.params

    @property
    def hlo_file_tup(self):
        """Return primary .hlo filename, filetype, and data keys for this action."""
        meta = self.json
        file_list = meta.get("files", [])
        hlo_files = [x for x in file_list if x["file_name"].endswith(".hlo")]
        if not hlo_files:
            return "", "", []
        first_hlo = hlo_files[0]
        retkeys = ["file_name", "file_type", "data_keys"]
        return [first_hlo.get(k, "") for k in retkeys]

    @property
    def hlo_file(self):
        """Return primary .hlo filename for this action."""
        return self.hlo_file_tup[0]

    @property
    def hlo(self):
        """Retrieve json data from S3 via HelaoLoader."""
        hlo_file = self.hlo_file
        if not hlo_file:
            return {}
        return self.loader.get_hlo(self.yml_path, hlo_file)

    def read_hlo_file(self, filename):
        return self.loader.get_hlo(self.yml_path, filename)


class HelaoExperiment(HelaoModel):
    """
        Represents a Helao experiment loaded from a local file system.

        Attributes:
            experiment_name (str): The name of the experiment.
            experiment_uuid (UUID): The unique identifier of the experiment.
            experiment_timestamp (datetime): The timestamp of the experiment.
            experiment_params (dict): The parameters of the experiment.

        Args:
            yml_path (str): The path to the YAML file containing the experiment definition.
            meta_dict (dict): A dictionary containing metadata associated with the experiment.
            loader (LocalLoader): The LocalLoader instance used to load the experiment.
    """
    experiment_name: str
    experiment_uuid: UUID
    experiment_timestamp: datetime
    experiment_params: dict

    def __init__(self, yml_path: str, meta_dict: dict, loader: LocalLoader):
        super().__init__(yml_path=yml_path, meta_dict=meta_dict, loader=loader)
        self.experiment_name = self.name
        self.experiment_uuid = self.uuid
        self.experiment_timestamp = self.timestamp
        self.experiment_params = self.params


class HelaoSequence(HelaoModel):
    """
        Represents a Helao sequence loaded from a local file system.

        Inherits from HelaoModel and includes additional attributes specific to sequences,
        such as sequence name, label, UUID, timestamp, and parameters.

        Attributes:
            sequence_name (str): The name of the sequence.
            sequence_label (str): A label associated with the sequence.
            sequence_uuid (UUID): The unique identifier of the sequence.
            sequence_timestamp (datetime): The timestamp of when the sequence was created or modified.
            sequence_params (dict): A dictionary containing the parameters of the sequence.

        Args:
            yml_path (str): The path to the YAML file containing the sequence definition.
            meta_dict (dict): A dictionary containing metadata associated with the sequence.
            loader (LocalLoader): The LocalLoader instance used to load the sequence.
    """
    sequence_name: str
    sequence_label: str
    sequence_uuid: UUID
    sequence_timestamp: datetime
    sequence_params: dict

    def __init__(self, yml_path: str, meta_dict: dict, loader: LocalLoader):
        super().__init__(yml_path=yml_path, meta_dict=meta_dict, loader=loader)
        self.sequence_name = self.name
        self.sequence_uuid = self.uuid
        self.sequence_timestamp = self.timestamp
        self.sequence_params = self.params
        self.sequence_label = meta_dict.get("sequence_label", "")

class HelaoProcess(HelaoModel):
    """
        Represents a Helao process with associated metadata and parameters.

        Attributes:
            technique_name (str): The name of the technique used in the process.
            process_uuid (UUID): The unique identifier for the process, inherited from the base model.
            process_timestamp (datetime): The timestamp of when the process was created, inherited from the base model.
            process_params (dict): A dictionary containing the parameters used in the process, inherited from the base model.

        Args:
            yml_path (str): The path to the YAML file containing the process definition.
            meta_dict (dict): A dictionary containing metadata associated with the process.
            loader (LocalLoader): The loader used to load the process definition.
    """
    technique_name: str
    process_uuid: UUID
    process_timestamp: datetime
    process_params: dict

    def __init__(self, yml_path: str, meta_dict: dict, loader: LocalLoader):
        super().__init__(yml_path=yml_path, meta_dict=meta_dict, loader=loader)
        self.process_uuid = self.uuid
        self.process_timestamp = self.timestamp
        self.process_params = self.params
        self.technique_name = self.name


class EcheUvisLoader(LocalLoader):
    """ECHEUVIS process dataloader

        This class is responsible for loading ECHEUVIS process data from a local file system.
        It inherits from the LocalLoader class and implements methods for retrieving recent data
        based on specified criteria such as minimum date, plate ID, and sample number.

        """
    def __init__(
        self,
        data_path: str
    ):
        super().__init__(data_path)

    def get_recent(
        self,
        query: str,
        min_date: str = "2023-04-26",
        plate_id: Optional[int] = None,
        sample_no: Optional[int] = None,
    ):
        """Retrieves recent data based on specified criteria.

            This method fetches data from the database that matches the given query and falls within the specified date range,
            optionally filtering by plate ID and sample number. It utilizes a caching mechanism to improve performance,
            retrieving data from the cache if available and applicable.

            Args:
                query (str): The base SQL query to execute.
                min_date (str, optional): The minimum date for the data to be retrieved, in 'YYYY-MM-DD' format.
                Defaults to "2023-04-26".
                plate_id (Optional[int], optional): The plate ID to filter the data by. Defaults to None.
                sample_no (Optional[int], optional): The sample number to filter the data by. Defaults to None.

            Returns:
                pd.DataFrame: A Pandas DataFrame containing the filtered data, sorted by process timestamp and reset index.
            """
        conditions = []
        conditions.append(f"    AND hp.process_timestamp >= '{min_date}'")
        recent_md = sorted(
            [md for md, pi, sn in self.recent_cache if pi is None and sn is None]
        )
        recent_mdpi = sorted(
            [md for md, pi, sn in self.recent_cache if pi == plate_id and sn is None]
        )
        recent_mdsn = sorted(
            [md for md, pi, sn in self.recent_cache if pi is None and sn == sample_no]
        )
        query_parts = ""
        if plate_id is not None:
            query_parts += f" & plate_id=={plate_id}"
        if sample_no is not None:
            query_parts += f" & sample_no=={sample_no}"

        if (
            min_date,
            plate_id,
            sample_no,
        ) not in self.recent_cache or not self.cache_sql:
            data = self.run_raw_query(query + "\n".join(conditions))
            pdf = pd.DataFrame(data)
            # print("!!! dataframe shape:", pdf.shape)
            # print("!!! dataframe cols:", pdf.columns)
            pdf["plate_id"] = pdf.global_label.apply(
                lambda x: int(x.split("_")[-2])
                if "solid" in x and "None" not in x
                else None
            )
            pdf["sample_no"] = pdf.global_label.apply(
                lambda x: int(x.split("_")[-1])
                if "solid" in x and "None" not in x
                else None
            )
            # assign solid samples from sequence params
            for suuid in set(pdf.query("sample_no.isna()").sequence_uuid):
                subdf = pdf.query("sequence_uuid==@suuid")
                spars = subdf.iloc[0]["sequence_params"]
                pid = spars["plate_id"]
                solid_samples = spars["plate_sample_no_list"]
                assemblies = sorted(
                    set(
                        subdf.query(
                            "global_label.str.contains('assembly')"
                        ).global_label
                    )
                )
                for slab, alab in zip(solid_samples, assemblies):
                    pdf.loc[
                        pdf.query("sequence_uuid==@suuid & global_label==@alab").index,
                        "plate_id",
                    ] = pid
                    pdf.loc[
                        pdf.query("sequence_uuid==@suuid & global_label==@alab").index,
                        "sample_no",
                    ] = slab
            # self.recent_cache[
            #     (
            #         min_date,
            #         plate_id,
            #         sample_no,
            #     )
            # ] = pdf.sort_values("process_timestamp")

        elif recent_md and min_date >= recent_md[0]:
            self.recent_cache[
                (
                    min_date,
                    plate_id,
                    sample_no,
                )
            ] = self.recent_cache[
                (
                    recent_md[0],
                    None,
                    None,
                )
            ].query(f"process_timestamp >= '{min_date}'" + query_parts)
        elif recent_mdpi and min_date >= recent_mdpi[0]:
            self.recent_cache[
                (
                    min_date,
                    plate_id,
                    sample_no,
                )
            ] = self.recent_cache[
                (
                    recent_mdpi[0],
                    plate_id,
                    None,
                )
            ].query(f"process_timestamp >= '{min_date}'" + query_parts)
        elif recent_mdsn and min_date >= recent_mdsn[0]:
            self.recent_cache[
                (
                    min_date,
                    plate_id,
                    sample_no,
                )
            ] = self.recent_cache[
                (
                    recent_mdsn[0],
                    None,
                    sample_no,
                )
            ].query(f"process_timestamp >= '{min_date}'" + query_parts)

        return self.recent_cache[
            (
                min_date,
                plate_id,
                sample_no,
            )
        ].reset_index(drop=True)
