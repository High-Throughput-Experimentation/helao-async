import os
import builtins
import json
from glob import glob
from uuid import UUID
from datetime import datetime
from zipfile import ZipFile
from collections import defaultdict

import pandas as pd

from helao.helpers.yml_tools import yml_load
# from helao.helpers.read_hlo import read_hlo
from helao.helpers.file_mapper import FileMapper

# yaml reader


class LocalLoader:
    """Provides cached access to local data."""

    def __init__(self, data_path: str):
        self.act_cache = {}  # {uuid: json_dict}
        self.exp_cache = {}
        self.seq_cache = {}
        self.pro_cache = {}
        self._yml_paths = {}
        self.target = os.path.abspath(os.path.normpath(data_path))
        if not os.path.exists(self.target):
            raise FileNotFoundError(
                "data_path argument is not a valid file or folder path"
            )
        if self.target.endswith(".zip"):
            with ZipFile(self.target, "r") as zf:
                zip_contents = zf.namelist()
            _yml_paths = [x for x in zip_contents if x.endswith(".yml")]
        elif os.path.isdir(self.target):
            _yml_paths = glob(os.path.join(self.target, "**", "*.yml"), recursive=True)
        else:
            _yml_paths = glob(
                os.path.join(os.path.dirname(self.target), "**", "*.yml"),
                recursive=True,
            )

        for suffix in ("seq", "exp", "act"):
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

    def clear_cache(self):
        self.act_cache = {}  # {uuid: json_dict}
        self.exp_cache = {}
        self.seq_cache = {}
        self.pro_cache = {}

    def get_yml(self, path: str):
        if self.target.endswith(".zip"):
            with ZipFile(self.target, "r") as zf:
                metad = yml_load(zf.open(path).read().decode("utf-8"))
        else:
            # metad = yml_load("".join(builtins.open(path, "r").readlines()))
            FM = FileMapper(path)
            metad = FM.read_yml(path)
        return metad

    def get_act(self, index=None, path: str = None):
        if index is None and path is None:
            raise IndexError("neither index, nor path arguments were supplied")
        if path is None:
            path = self.actions.iloc[index].action_localpath
        metad = self.act_cache.get(path, self.get_yml(path))
        self.act_cache[path] = metad
        return HelaoAction(path, metad, self)

    def get_exp(self, index=None, path: str = None):
        if index is None and path is None:
            raise IndexError("neither index, nor path arguments were supplied")
        if path is None:
            path = self.experiments.iloc[index].experiment_localpath
        metad = self.exp_cache.get(path, self.get_yml(path))
        self.exp_cache[path] = metad
        return HelaoExperiment(path, metad, self)

    def get_seq(self, index=None, path: str = None):
        if index is None and path is None:
            raise IndexError("neither index, nor path arguments were supplied")
        if path is None:
            path = self.sequences.iloc[index].sequence_localpath
        metad = self.seq_cache.get(path, self.get_yml(path))
        self.seq_cache[path] = metad
        return HelaoSequence(path, metad, self)

    def get_hlo(self, yml_path: str, hlo_fn: str):
        if self.target.endswith(".zip"):
            hlotarget = os.path.join(os.path.dirname(yml_path), hlo_fn)
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


ABBR_MAP = {"act": "action", "exp": "experiment", "seq": "sequence"}


class HelaoModel:
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
        self.name = meta_dict[f"{helao_type}_name"]
        self.uuid = meta_dict[f"{helao_type}_uuid"]
        self.timestamp = meta_dict[f"{helao_type}_timestamp"]
        self.params = meta_dict[f"{helao_type}_params"]
        self.meta_dict = meta_dict
        self.loader = loader

    @property
    def json(self):
        return self.meta_dict


class HelaoAction(HelaoModel):
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
    def hlo_file(self):
        """Return primary .hlo filename for this action."""
        meta = self.json
        file_list = meta.get("files", [])
        hlo_files = [x for x in file_list if x["file_name"].endswith(".hlo")]
        if not hlo_files:
            return ""
        filename = hlo_files[0]["file_name"]
        return filename

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
