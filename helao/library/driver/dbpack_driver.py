__all__ = ["DBPack", "ActYml", "ExpYml", "HelaoPath"]

import os
import io
import codecs
import json
import yaml
import configparser
from pathlib import Path
from glob import glob
from datetime import datetime
from typing import Union
from collections import UserDict, defaultdict

import pyaml
import botocore
import boto3
from helaocore.server.base import Base
from helaocore.model.process import ProcessModel
from helaocore.model.action import ShortActionModel, ActionModel
from helaocore.model.experiment import ExperimentModel
from helaocore.model.experiment_sequence import ExperimentSequenceModel
from helaocore.helper.gen_uuid import gen_uuid
from helaocore.helper.read_hlo import read_hlo

# from helaocore.error import ErrorCodes

# from helaocore.model.sample import (
#     SampleUnion,
#     AssemblySample,
#     NoneSample,
#     SampleStatus,
#     SampleInheritance,
#     object_to_sample,
# )

# from helaocore.helper.print_message import print_message
# from helaocore.data.sample import UnifiedSampleDataAPI

# progress dict has 3 (for action) or 4 (for sequence) or 5 (for experiment) keys:
# 1) API push [datetime]
# 2) files push Dict(filename, datetime)
# 3) yml push [datetime]
# 4) archived group statuses: Dict(order_key: )
# 5) ordered processes: Dict(process_timestamp, process_yml)

test_flag = False

modmap = {
    "action": ActionModel,
    "experiment": ExperimentModel,
    "sequence": ExperimentSequenceModel,
}


def dict2json(input_dict: dict):
    """Converts dict to file-like object containing json."""
    bio = io.BytesIO()
    StreamWriter = codecs.getwriter("utf-8")
    wrapper_file = StreamWriter(bio)
    json.dump(input_dict, wrapper_file)
    bio.seek(0)
    return bio


class HelaoPath(type(Path())):
    """Helao data path helper attributes."""

    def __str__(self):
        return os.path.join(*self.parts)

    def rename(self, status: str):
        tempparts = list(self.parts)
        tempparts[self.status_idx] = status
        return HelaoPath(os.path.join(*tempparts))

    @property
    def status_idx(self):
        valid_statuses = ("ACTIVE", "FINISHED", "SYNCED")
        return [any([x in valid_statuses]) for x in self.parts].index(True)

    @property
    def relative(self):
        return "/".join(list(self.parts)[self.status_idx + 1 :])

    @property
    def active(self):
        return self.rename("ACTIVE")

    @property
    def finished(self):
        return self.rename("FINISHED")

    @property
    def synced(self):
        return self.rename("SYNCED")

    def cleanup(self):
        """Remove empty directories in ACTIVE or FINISHED."""
        tempparts = list(self.parts)
        steps = len(tempparts) - self.status_idx
        for i in range(1, steps):
            check_dir = Path(os.path.join(*tempparts[:-i]))
            contents = [x for x in check_dir.glob("*") if x != check_dir]
            if contents:
                break
            check_dir.rmdir()


class HelaoYml:
    def __init__(self, yml_path: Union[HelaoPath, str], dry_run: bool = test_flag):
        self.dry_run = dry_run
        self.parse_yml(yml_path)

    def parse_yml(self, yml_path):
        self.target = (
            yml_path if isinstance(yml_path, HelaoPath) else HelaoPath(yml_path)
        )
        self.yml_dict = yaml.safe_load(self.target.read_text())
        self.yml_type = self.yml_dict["file_type"]
        self.yml_key = HelaoPath(self.yml_dict[f"{self.yml_type}_output_dir"]).stem
        self.status = self.target.parts[self.target.parts.index("INST") + 1]
        self.data_dir = self.target.parent
        self.data_files = [
            x
            for x in self.data_dir.glob("*")
            if x.suffix not in [".yml", ".progress"] and x.is_file()
        ]
        self.parent_dir = self.data_dir.parent
        syncpath_offset = {"action": -6, "experiment": -6, "sequence": -5}
        if self.yml_type == "action":
            exp_parts = list(self.target.parent.parent.parts)
            exp_parts[-5] = "*"
            exp_parts.append("*.yml")
            all_exp_paths = glob(os.path.join(*exp_parts))
            progress_parts = list(HelaoPath(all_exp_paths[0]).parts)
        else:
            progress_parts = list(self.target.parts)
        progress_parts[syncpath_offset[self.yml_type]] = "SYNCED"
        progress_parts[-1] = progress_parts[-1].replace(".yml", ".progress")
        self.progress_path = HelaoPath(os.path.join(*progress_parts))
        self.progress = Progress(self)
        if self.status == "FINISHED":
            self.progress[self.yml_key]["ready"] = True
            self.progress[self.yml_key]["meta"] = modmap[self.yml_type](
                **self.yml_dict
            ).clean_dict()
            self.progress.write()

    @property
    def time(self):
        return datetime.strptime(
            self.yml_dict[f"{self.yml_type}_timestamp"], "%Y-%m-%d %H:%M:%S.%f"
        )

    @property
    def name(self):
        return self.yml_dict[f"{self.yml_type}_name"]


class Progress(UserDict):
    """Custom dict that wraps getter/setter ops with read/writes to progress file.

    Note: getter-setter ops only work for root keys, setting a nested key-value requires
    an additional call to Progress.write()
    """

    def __init__(self, pack_yml: HelaoYml):
        super().__init__()
        self.pack_yml = pack_yml
        self.yml_key = pack_yml.yml_key
        self.progress_path = pack_yml.progress_path
        self.data_files = pack_yml.data_files
        self.read()
        if self.yml_key not in self.data.keys():
            self.data[self.yml_key] = {
                "ready": False,  # ready to start transfer from FINISHED to SYNCED
                "done": False,  # same as status=='SYNCED'
                "meta": None,
                "files_pending": [x.__str__() for x in self.data_files],
                "files_pushed": {},
                "api_pushed": False,
                "s3_pushed": False,
            }
            self.write()

    def read(self):
        if self.progress_path.exists():
            self.data = yaml.safe_load(self.progress_path.read_text())

    def write(self):
        self.progress_path.parent.mkdir(parents=True, exist_ok=True)
        self.progress_path.write_text(pyaml.dump(self.data, safe=True))

    def __setitem__(self, key, item):
        self.data[key] = item
        self.write()

    def __getitem__(self, key):
        self.read()
        return self.data[key]

    def __repr__(self):
        self.read()
        return repr(self.data)

    def __len__(self):
        self.read()
        return len(self.data)

    def __delitem__(self, key):
        del self.data[key]
        self.write()

    def has_key(self, k):
        self.read()
        return k in self.data

    def update(self, *args, **kwargs):
        self.read()
        self.data.update(*args, **kwargs)
        self.write()

    def keys(self):
        self.read()
        return self.data.keys()

    def values(self):
        self.read()
        return self.data.values()

    def items(self):
        self.read()
        return self.data.items()

    def pop(self, *args):
        self.read()
        retval = self.data.pop(*args)
        return retval

    def __cmp__(self, dict_):
        self.read()
        return self.__cmp__(self.data, dict_)

    def __contains__(self, item):
        self.read()
        return item in self.data

    def __iter__(self):
        self.read()
        return iter(self.data)


class ActYml(HelaoYml):
    def __init__(self, yml_path: Union[HelaoPath, str]):
        super().__init__(yml_path)
        self.finisher = self.yml_dict.get("process_finish", False)
        self.contribs = self.yml_dict.get("process_contrib", False)


class ExpYml(HelaoYml):
    def __init__(self, yml_path: Union[HelaoPath, str]):
        super().__init__(yml_path)
        self.get_actions()
        self.max_group = max(self.grouped_actions.keys())

    def get_actions(self):
        """Return a list of ActYml objects belonging to this experiment."""
        action_parts = list(self.data_dir.parts)
        action_parts[-5] = "*"
        action_parts.append(f"*{os.sep}*.yml")
        all_action_paths = glob(os.path.join(*action_parts))

        self.current_actions = sorted(
            [ActYml(ap) for ap in all_action_paths], key=lambda x: x.time
        )
        self.update_groups()
        self.update_group_progress()

    def update_groups(self):
        """Populate dict of process-grouped actions and list of ungrouped actions."""
        self.grouped_actions = defaultdict(list)
        self.ungrouped_actions = []
        current_idx = 0
        for act in self.current_actions:
            if act.contribs:
                self.grouped_actions[current_idx].append(act)
                if act.finisher:
                    current_idx += 1
            else:
                self.ungrouped_actions.append(act)

    def update_group_progress(self):
        for group_idx, group_acts in self.grouped_actions.items():
            # init new groups
            if group_idx not in self.progress.keys():
                print("creating group", group_idx)
                self.progress[group_idx] = {
                    "ready": False,  # ready to start transfer from FINISHED to SYNCED
                    "done": False,  # status=='SYNCED' for all constituents, api, s3
                    "meta": None,
                    "pending": [],
                    "pushed": {},
                    "api": False,
                    "s3": False,
                }
                self.progress.write()
            if self.progress[group_idx]["done"]:
                continue
            if all([self.progress[act.yml_key]["ready"] for act in group_acts]):
                self.progress[group_idx]["ready"] = True
                self.progress.write()
                if self.progress[group_idx]["meta"] is None:
                    self.create_process(group_idx)

    def create_process(self, group_idx: int):
        """Create process group from finished actions in progress['meta']."""
        actions = self.grouped_actions[group_idx]
        base_process = {
            k: self.yml_dict[k]
            for k in (
                "access",
                "orchestrator",
                "technique_name",
                "sequence_uuid",
                "experiment_uuid",
            )
        }
        base_process.update(
            {
                "process_timestamp": actions[0].time,
                "process_group_index": group_idx,
                "process_uuid": gen_uuid(),
                "process_name": actions[-1].name,
                "action_list": [
                    ShortActionModel(**act.yml_dict)
                    for act in self.grouped_actions[group_idx]
                ],
            }
        )
        fill_process = {
            "action_params": {},
            "samples_in": [],
            "samples_out": [],
            "files": [],
        }
        for act in actions:
            for ppkey, ppval in fill_process.items():
                if ppkey in act.contribs:
                    if isinstance(ppval, dict):
                        adict = act.yml_dict.get(ppkey, {})
                        fill_process[ppkey].update(adict)
                    elif isinstance(ppval, list):
                        alist = act.yml_dict.get(ppkey, [])
                        fill_process[ppkey] += alist
                    else:  # overwrite scalars newest/latest action
                        if ppkey in act.yml_dict.keys():
                            fill_process[ppkey] = act.yml_dict[ppkey]
            # populate 'pending' files list
            if "files" in act.contribs:
                for data_path in act.data_files:
                    self.progress[group_idx]["pending"].append(data_path.__str__())
                    self.progress.write()
        fill_process["process_params"] = fill_process.pop("action_params")
        base_process.update(fill_process)
        self.progress[group_idx]["meta"] = ProcessModel(**base_process).clean_dict()
        self.progress.write()


class SeqYml(HelaoYml):
    def __init__(self, yml_path: Union[HelaoPath, str]):
        super().__init__(yml_path)
        self.get_experiments()

    def get_experiments(self):
        """Return a list of ExpYml objects belonging to this experiment."""
        experiment_parts = list(self.data_dir.parts)
        experiment_parts[-4] = "*"
        experiment_parts.append(f"*{os.sep}*.yml")
        all_experiment_paths = glob(os.path.join(*experiment_parts))

        self.current_experiments = sorted(
            [ExpYml(ep) for ep in all_experiment_paths], key=lambda x: x.time
        )

    def update_progress(self):
        for group_idx, group_acts in self.grouped_actions.items():
            # init new groups
            if group_idx not in self.progress.keys():
                print("creating group", group_idx)
                self.progress[group_idx] = {
                    "ready": False,  # ready to start transfer from FINISHED to SYNCED
                    "done": False,  # status=='SYNCED' for all constituents, api, s3
                    "meta": None,
                    "pending": [],
                    "pushed": {},
                    "api": False,
                    "s3": False,
                }
                self.progress.write()
            if self.progress[group_idx]["done"]:
                continue
            if all([self.progress[act.yml_key]["ready"] for act in group_acts]):
                self.progress[group_idx]["ready"] = True
                self.progress.write()
                if self.progress[group_idx]["meta"] is None:
                    self.create_process(group_idx)

    def sync_sequence(self):
        """Push finished sequence, upload yml to S3."""
        pass


class DBPack:
    """Driver class for API push and S3 upload operations.

    config_dict = {
        "aws_config_path": "path_to_AWS_CONFIG_FILE",
        "aws_bucket": "helao.data.testing"
    }
    """

    def __init__(self, action_serv: Base):
        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.world_config = action_serv.world_cfg
        self.aws_config = configparser.ConfigParser()
        self.aws_config.read(self.config_dict["aws_config_path"])["default"]
        self.aws_session = boto3.Session(
            region_name=self.aws_config["region"],
            aws_access_key_id=self.aws_config["aws_access_key_id"],
            aws_secret_access_key=self.aws_config["aws_secret_access_key"],
        )
        self.bucket = self.aws_config["aws_bucket"]
        self.s3 = self.aws_session.client("s3")


class YmlOps:
    def __init__(self, dbp: DBPack, helao_yml: Union[ActYml, ExpYml, SeqYml]):
        self.dbp = dbp
        self.yml = helao_yml

    def to_api(self, progress_key: Union[str, int], retry_num: int = 5):
        """Submit to modelyst DB"""
        # create http request
        # post request
        # verify success and retry
        pass

    def _to_s3(self, input: Union[dict, str], target: str, retry_num: int = 5):
        if isinstance(input, dict):
            uploaded = dict2json(input)
            uploader = self.dbp.s3.upload_fileobj
        else:
            uploader = self.dbp.s3.upload_file
        for i in range(retry_num):
            try:
                uploader(uploaded, self.dbp.bucket, target)
                return True
            except botocore.exceptions.ClientError as e:
                self.dbp.base.print_message(e)
                self.dbp.base.print_message(
                    f"Retry S3 upload [{i}/{retry_num}]: {self.dbp.bucket}, {target}"
                )
        return False

    def to_s3(self, progress_key: Union[str, int], retry_num: int = 5):
        """Upload data_files and yml/json to S3"""

        pdict = self.yml.progress[progress_key]
        tech = self.dbp.world_config["technique_name"]
        if isinstance(progress_key, int):  # process group
            meta_type = "process"
        else:
            meta_type = self.yml.yml_type.lower()

        # push
        meta_s3_key = f"{meta_type}/{tech}/{self.yml.target.relative}.json"
        meta_success = self._to_s3(pdict["meta"], meta_s3_key)
        if meta_success:
            pdict["s3"] = True
            self.yml.progress.write()

        hlo_data = [x for x in self.yml.data_files if x.name.endswith(".hlo")]
        aux_data = [x for x in self.yml.data_files if not x.name.endswith(".hlo")]
        # create s3 api request
        # post request
        # verify success and retry
        pass

    def to_finished(self):
        """Moves yml and data folder from ACTIVE to FINISHED path."""
        if self.yml.status == "ACTIVE":
            if self.yml.dry_run:
                print("Moving files:")
                for file_path in self.yml.data_files:
                    print(file_path.finished)
                print(self.yml.target.finished)
                return
            for file_path in self.yml.data_files:
                file_path.finished.parent.mkdir(parents=True, exist_ok=True)
                file_path.replace(file_path.finished)
            self.yml.target.finished.parent.mkdir(parents=True, exist_ok=True)
            new_target = self.yml.target.replace(self.target.finished)
            self.yml.target.cleanup()
            self.yml.parse_yml(new_target)
        else:
            print("Yml status is not ACTIVE, cannot move.")

    def to_synced(self):
        """Moves yml and data folder from FINISHED to SYNCED path. Final state."""
        if self.yml.status == "FINISHED" and self.progress[self.yml_key]["done"]:
            if self.yml.dry_run:
                print("Moving files:")
                for file_path in self.yml.data_files:
                    print(file_path.synced)
                print(self.yml.target.synced)
                return
            for file_path in self.yml.data_files:
                file_path.synced.parent.mkdir(parents=True, exist_ok=True)
                file_path.replace(file_path.synced)
            self.yml.target.synced.parent.mkdir(parents=True, exist_ok=True)
            new_target = self.yml.target.replace(self.target.synced)
            self.yml.target.cleanup()
            self.yml.parse_yml(new_target)
