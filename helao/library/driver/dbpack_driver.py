__all__ = ["DBPack", "ActYml", "ExpYml", "SeqYml", "HelaoPath", "YmlOps"]

import os
import io
import codecs
import json
import configparser
import asyncio
from ruamel.yaml import YAML
from pathlib import Path
from glob import glob
from datetime import datetime
from typing import Union
from collections import UserDict, defaultdict
from enum import Enum

import pyaml
import botocore
import boto3
import aiohttp
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
    "process": ProcessModel,
}
plural = {
    "action": "actions",
    "experiment": "experiments",
    "sequence": "sequences",
    "process": "processes",
}


class YmlType(str, Enum):
    action = "action"
    experiment = "experiment"
    sequence = "sequence"


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
        valid_statuses = ("RUNS_ACTIVE", "RUNS_FINISHED", "RUNS_SYNCED")
        return [any([x in valid_statuses]) for x in self.parts].index(True)

    @property
    def relative(self):
        return "/".join(list(self.parts)[self.status_idx + 1 :])

    @property
    def active(self):
        return self.rename("RUNS_ACTIVE")

    @property
    def finished(self):
        return self.rename("RUNS_FINISHED")

    @property
    def synced(self):
        return self.rename("RUNS_SYNCED")

    def cleanup(self):
        """Remove empty directories in RUNS_ACTIVE or RUNS_FINISHED."""
        tempparts = list(self.parts)
        steps = len(tempparts) - self.status_idx
        for i in range(1, steps):
            check_dir = Path(os.path.join(*tempparts[:-i]))
            contents = [x for x in check_dir.glob("*") if x != check_dir]
            if contents:
                break
            try:
                check_dir.rmdir()
                return "success"
            except PermissionError as e:
                return e


class HelaoYml:
    def __init__(self, path: Union[HelaoPath, str], dry_run: bool = test_flag):
        self.dry_run = dry_run
        self.parse_yml(path)

    def parse_yml(self, path):
        self.target = path if isinstance(path, HelaoPath) else HelaoPath(path)
        yaml = YAML(typ="safe")
        self.dict = yaml.load(self.target)
        self.type = self.dict["file_type"]
        self.uuid = self.dict[f"{self.type}_uuid"]
        self.pkey = HelaoPath(self.dict[f"{self.type}_output_dir"]).stem
        self.status = self.target.parts[self.target.parts.index("INST") + 1].replace("RUNS_","")
        self.data_dir = self.target.parent
        self.data_files = [
            x
            for x in self.data_dir.glob("*")
            if x.suffix not in [".yml", ".progress"] and x.is_file()
        ]
        self.parent_dir = self.data_dir.parent
        syncpath_offset = {"action": -6, "experiment": -6, "sequence": -5}
        if self.type == "action":
            exp_parts = list(self.target.parent.parent.parts)
            exp_parts[-5] = "*"
            exp_parts.append("*.yml")
            all_exp_paths = glob(os.path.join(*exp_parts))
            progress_parts = list(HelaoPath(all_exp_paths[0]).parts)
        else:
            progress_parts = list(self.target.parts)
        progress_parts[syncpath_offset[self.type]] = "RUNS_SYNCED"
        progress_parts[-1] = progress_parts[-1].replace(".yml", ".progress")
        self.progress_path = HelaoPath(os.path.join(*progress_parts))
        self.progress = Progress(self)
        meta_json = modmap[self.type](**self.dict).clean_dict()
        for file_dict in meta_json.get("files", []):
            if file_dict["file_name"].endswith(".hlo"):
                file_dict["file_name"] = f"{file_dict['file_name']}.json"
        if self.status == "FINISHED":
            self.progress[self.pkey].update({"ready": True, "meta": meta_json})
            self.progress.write()

    @property
    def time(self):
        return datetime.strptime(
            self.dict[f"{self.type}_timestamp"], "%Y-%m-%d %H:%M:%S.%f"
        )

    @property
    def name(self):
        return self.dict[f"{self.type}_name"]


class Progress(UserDict):
    """Custom dict that wraps getter/setter ops with read/writes to progress file.

    Note: getter-setter ops only work for root keys, setting a nested key-value requires
    an additional call to Progress.write()
    """

    def __init__(self, yml: HelaoYml):
        super().__init__()
        self.yml = yml
        self.pkey = yml.pkey
        self.progress_path = yml.progress_path
        self.read()
        if self.pkey not in self.data.keys():
            self.data[self.pkey] = {
                "ready": False,  # ready to start transfer from FINISHED to SYNCED
                "done": False,  # same as status=='SYNCED'
                "meta": None,
                "type": self.yml.type,
                "pending": [],
                "pushed": {},
                "api": False,
                "s3": False,
            }
            self.write()
        pending_files = [
            str(x)
            for x in yml.data_files
            if x.name not in self.data[self.pkey]["pushed"].keys()
        ]
        self.data[self.pkey]["pending"] = pending_files
        self.data[self.pkey]["path"] = str(yml.target)
        self.write()

    def read(self):
        if self.progress_path.exists():
            yaml = YAML(typ="safe")
            self.data = yaml.load(self.progress_path)

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
    def __init__(self, path: Union[HelaoPath, str]):
        super().__init__(path)
        self.finisher = self.dict.get("process_finish", False)
        self.contribs = self.dict.get("process_contrib", False)


class ExpYml(HelaoYml):
    def __init__(self, path: Union[HelaoPath, str]):
        super().__init__(path)
        self.get_actions()
        if self.grouped_actions:
            self.max_group = max(self.grouped_actions.keys())
        else:
            self.max_group = 0

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
                    "type": "process",
                    "pending": [],
                    "pushed": {},
                    "api": False,
                    "s3": False,
                }
                self.progress.write()
            if self.progress[group_idx]["done"]:
                continue
            if all([self.progress[act.pkey]["ready"] for act in group_acts]):
                self.progress[group_idx]["ready"] = True
                self.progress.write()
                if self.progress[group_idx]["meta"] is None:
                    self.create_process(group_idx)

    def create_process(self, group_idx: int):
        """Create process group from finished actions in progress['meta']."""
        actions = self.grouped_actions[group_idx]
        base_process = {
            k: self.dict[k]
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
                    ShortActionModel(**act.dict)
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
                        adict = act.dict.get(ppkey, {})
                        fill_process[ppkey].update(adict)
                    elif isinstance(ppval, list):
                        alist = act.dict.get(ppkey, [])
                        fill_process[ppkey] += alist
                    else:  # overwrite scalars newest/latest action
                        if ppkey in act.dict.keys():
                            fill_process[ppkey] = act.dict[ppkey]
            # populate 'pending' files list
            if "files" in act.contribs:
                for data_path in act.data_files:
                    self.progress[group_idx]["pending"].append(data_path.__str__())
                    self.progress.write()
        fill_process["process_params"] = fill_process.pop("action_params")
        base_process.update(fill_process)
        meta_json = ProcessModel(**base_process).clean_dict()
        for file_dict in meta_json["files"]:
            if file_dict["file_name"].endswith(".hlo"):
                file_dict["file_name"] = f"{file_dict['file_name']}.json"
        self.progress[group_idx]["meta"] = meta_json
        self.progress.write()


class SeqYml(HelaoYml):
    def __init__(self, path: Union[HelaoPath, str]):
        super().__init__(path)
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


ymlmap = {
    "action": ActYml,
    "experiment": ExpYml,
    "sequence": SeqYml,
}


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
        self.aws_config.read(self.config_dict["aws_config_path"])
        self.aws_config = self.aws_config["default"]
        self.aws_session = boto3.Session(
            region_name=self.aws_config["region"],
            aws_access_key_id=self.aws_config["aws_access_key_id"],
            aws_secret_access_key=self.aws_config["aws_secret_access_key"],
        )
        self.bucket = self.aws_config["aws_bucket"]
        self.s3 = self.aws_session.client("s3")
        self.api_host = self.aws_config["api_host"]

    async def finish_exps(self, seq_yml: SeqYml):
        seq_yml.get_experiments()
        for exp in seq_yml.current_experiments:
            if exp.status != "SYNCED":
                await self.finish_acts(exp)
                await self.finish_yml(exp.target, YmlType.experiment)

    async def finish_acts(self, exp_yml: ExpYml):
        exp_yml.get_actions()
        for act in exp_yml.current_actions:
            if act.status != "SYNCED":
                await self.finish_yml(act.target, YmlType.action)

    async def finish_yml(self, yml_path: Union[str, HelaoPath], yml_type: YmlType):
        """Primary function for processing ymls.

        Args
        yml_path[str]: local path to yml file
        yml_type[YmlType]: type enum (YmlType.action, YmlType.experiment...)

        """
        hpth = HelaoPath(yml_path) if isinstance(yml_path, str) else yml_path
        hyml = ymlmap[yml_type](hpth)
        ops = YmlOps(self, hyml)

        # if given a sequence or experiment, recurse through constituents
        if yml_type == YmlType.sequence:
            await self.finish_exps(hyml)
        elif yml_type == YmlType.experiment:
            await self.finish_acts(hyml)

        # finish_yml request should be posted by orchestrator when act/exp/seq completes
        # calling this method assumes this yml and associated data are complete
        if hyml.status == "ACTIVE":
            ops.to_finished()

        # update progress again after finishing constituents
        if yml_type == YmlType.sequence:
            hyml.get_experiments()
        elif yml_type == YmlType.experiment:
            hyml.get_actions()

        # check all 'ready', ignore all 'done'
        progress = hyml.progress
        finished = []

        # first pass, check for pending uploads
        for pkey, pdict in progress.items():
            if pdict["done"]:
                continue
            if pdict["ready"]:
                if pdict["pending"] or not pdict["s3"]:
                    await ops.to_s3(pkey)

        # refresh progress and re-check finished s3
        progress.read()
        for pkey, pdict in progress.items():
            if pdict["done"]:
                continue
            if len(pdict["pending"]) == 0 and pdict["s3"]:
                await ops.to_api(pkey)

        # refresh progress and re-check finished s3
        progress.read()
        for pkey, pdict in progress.items():
            if pdict["done"]:
                continue
            if pdict["api"]:
                if isinstance(pkey, str):
                    ops.to_synced()
                pdict["done"] = True
                pdict["ready"] = False
                progress.write()
                finished.append(pkey)

        return_dict = {
            k: {dk: dv for dk, dv in d.items() if dk != "meta"}
            for k, d in progress.items()
            if k in finished
        }
        return return_dict


class YmlOps:
    def __init__(self, dbp: DBPack, yml: Union[ActYml, ExpYml, SeqYml]):
        self.dbp = dbp
        self.yml = yml

    async def to_api(self, progress_key: Union[str, int], retry_num: int = 3):
        """Submit to modelyst DB"""
        # no pending files, yml pushed to S3
        pdict = self.yml.progress[progress_key]
        if pdict["pending"] or not pdict["s3"]:
            self.dbp.base.print_message("Cannot push to API with S3 upload pending.")
            return False
        meta_type = pdict["type"]
        req_model = modmap[meta_type](**pdict["meta"]).clean_dict()
        req_url = f"http://{self.dbp.api_host}/{plural[meta_type]}"
        async with aiohttp.ClientSession() as session:
            for i in range(retry_num):
                async with session.post(req_url, json=req_model) as resp:
                    if resp.status == 200:
                        self.dbp.base.print_message(f"API post {self.yml.uuid} success")
                        return True
                    else:
                        self.dbp.base.print_message(
                            f"API post {self.yml.uuid} failed with status {resp.status}"
                        )
                        self.dbp.base.print_message(
                            f"Retry API [{i}/{retry_num}]: {self.yml.uuid}"
                        )
                        await asyncio.sleep(1)
        self.dbp.base.print_message(
            f"Did not post {self.yml.uuid} after {retry_num} tries."
        )
        return False

    async def _to_s3(self, msg: Union[dict, str], target: str, retry_num: int):
        if isinstance(msg, dict):
            uploaded = dict2json(msg)
            uploader = self.dbp.s3.upload_fileobj
        else:
            uploaded = msg
            uploader = self.dbp.s3.upload_file
        for i in range(retry_num):
            try:
                uploader(uploaded, self.dbp.bucket, target)
                self.dbp.base.print_message(f"Successfully uploaded {target}")
                return True
            except botocore.exceptions.ClientError as e:
                self.dbp.base.print_message(e)
                self.dbp.base.print_message(
                    f"Retry S3 upload [{i}/{retry_num}]: {self.dbp.bucket}, {target}"
                )
                await asyncio.sleep(1)
        self.dbp.base.print_message(f"Did not upload {target} after {retry_num} tries.")
        return False

    async def to_s3(self, progress_key: Union[str, int], retry_num: int = 3):
        """Upload data_files and yml/json to S3"""

        pdict = self.yml.progress[progress_key]
        if isinstance(progress_key, int):  # process group
            meta_type = "process"
        else:
            meta_type = self.yml.type.lower()

        hlo_data = [x for x in pdict["pending"] if x.endswith(".hlo")]
        for fpath in hlo_data:
            file_s3_key = f"raw_data/{self.yml.uuid}/{os.path.basename(fpath)}.json"
            file_meta, file_data = read_hlo(fpath)
            file_json = {"meta": file_meta, "data": file_data}
            file_success = await self._to_s3(file_json, file_s3_key, retry_num)
            if file_success:
                pdict["pending"].remove(fpath)
                pdict["pushed"].update({os.path.basename(fpath): datetime.now()})
                self.yml.progress.write()

        aux_data = [x for x in pdict["pending"] if not x.endswith(".hlo")]
        for fpath in aux_data:
            file_s3_key = f"raw_data/{self.yml.uuid}/{os.path.basename(fpath)}.json"
            file_success = await self._to_s3(fpath, file_s3_key, retry_num)
            if file_success:
                pdict["pending"].remove(fpath)
                pdict["pushed"].update({os.path.basename(fpath): datetime.now()})
                self.yml.progress.write()

        if not pdict["s3"]:
            meta_s3_key = f"{meta_type}/{self.yml.uuid}.json"
            meta_success = await self._to_s3(pdict["meta"], meta_s3_key, retry_num)
            if meta_success:
                pdict["s3"] = True
                self.yml.progress.write()

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
            new_target = self.yml.target.replace(self.yml.target.finished)
            clean_success = self.yml.target.cleanup()
            if clean_success != "success":
                self.dbp.base.print_message("Could not clean directory after moving.")
                self.dbp.base.print_message(clean_success)
            self.yml.parse_yml(new_target)
        else:
            print("Yml status is not ACTIVE, cannot move.")

    def to_synced(self):
        """Moves yml and data folder from FINISHED to SYNCED path. Final state."""
        if self.yml.status == "FINISHED":
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
            new_target = self.yml.target.replace(self.yml.target.synced)
            clean_success = self.yml.target.cleanup()
            if clean_success != "success":
                self.dbp.base.print_message("Could not clean directory after moving.")
                self.dbp.base.print_message(clean_success)
            self.yml.parse_yml(new_target)
