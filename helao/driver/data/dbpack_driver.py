__all__ = ["DBPack", "ActYml", "ExpYml", "SeqYml", "HelaoPath", "YmlOps"]

import os
import io
import codecs
import json
import asyncio
from time import sleep
from ruamel.yaml import YAML
from pathlib import Path
from glob import glob
from datetime import datetime
from typing import Union, Optional
from collections import UserDict, defaultdict
import traceback

import pyaml
import botocore
import boto3
import aiohttp
from helaocore.error import ErrorCodes
from helaocore.server.base import Base
from helaocore.model.process import ProcessModel
from helaocore.model.action import ShortActionModel, ActionModel
from helaocore.model.experiment import ExperimentModel
from helaocore.model.experiment_sequence import ExperimentSequenceModel
from helaocore.helper.gen_uuid import gen_uuid
from helaocore.helper.read_hlo import read_hlo
from helao.driver.data.enum import YmlType


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
                tb = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
                return e


class HelaoYml:
    def __init__(self, path: Union[HelaoPath, str], uuid_test: Optional[dict] = None):
        self.uuid_test = uuid_test  # regenerate uuid for testing
        self.parse_yml(path)

    def parse_yml(self, path):
        self.target = path if isinstance(path, HelaoPath) else HelaoPath(path)
        yaml = YAML(typ="safe")
        self.dict = yaml.load(self.target)
        self.type = self.dict["file_type"]
        self.uuid = self.dict[f"{self.type}_uuid"]
        # overwrite uuid when test dict is passed by dbp server
        if self.uuid_test is not None:
            if self.target.__str__() not in self.uuid_test.keys():
                self.uuid_test[self.target.__str__()] = gen_uuid()
            self.uuid = self.uuid_test[self.target.__str__()]
        self.pkey = HelaoPath(self.dict[f"{self.type}_output_dir"]).stem
        self.pkey = f"{self.type}--" + self.pkey
        inst_idx = [i for i, p in enumerate(self.target.parts) if "INST" in p]
        if inst_idx:
            inst_idx = inst_idx[0]
        else:
            print("'INST' directory was not found in yml path. Cannot proceed.")
            return False
        self.status = self.target.parts[inst_idx + 1].replace("RUNS_", "")
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
            if self.type == "experiment":
                group_keys = sorted(
                    [k for k in self.progress.keys() if isinstance(k, int)]
                )
                process_metas = [self.progress[k]["meta"] for k in group_keys]
                if any([p is None for p in process_metas]):
                    return None
                process_list = [pm["process_uuid"] for pm in process_metas]
                meta_json["process_list"] = process_list
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
        self.data[self.pkey].update({"pending": pending_files, "path": str(yml.target)})
        self.write()

    def read(self):
        if self.progress_path.exists():
            yaml = YAML(typ="safe")
            self.data = yaml.load(self.progress_path)

    def write(self):
        self.progress_path.parent.mkdir(parents=True, exist_ok=True)
        self.progress_path.write_text(
            pyaml.dump(self.data, safe=True, sort_dicts=False)
        )

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
    def __init__(self, path: Union[HelaoPath, str], **kwargs):
        super().__init__(path, **kwargs)
        self.finisher = self.dict.get("process_finish", False)
        self.contribs = self.dict.get("process_contrib", False)


class ExpYml(HelaoYml):
    def __init__(self, path: Union[HelaoPath, str], **kwargs):
        super().__init__(path, **kwargs)
        self.grouped_actions = defaultdict(list)
        self.ungrouped_actions = []
        self.current_actions = []
        self.get_actions()
        if self.grouped_actions:
            self.max_group = max(self.grouped_actions.keys())
        else:
            self.max_group = 0
        # init again to refresh action and process list
        super().__init__(path, **kwargs)

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
            self.progress.read()
            if group_idx not in self.progress.keys():
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
            self.progress.read()
            if all(
                [
                    self.progress[act.pkey]["ready"] or self.progress[act.pkey]["done"]
                    for act in group_acts
                ]
            ):
                self.progress[group_idx]["ready"] = True
                self.progress.write()
                if self.progress[group_idx].get("meta", None) is None:
                    self.create_process(group_idx)

    def create_process(self, group_idx: int):
        """Create process group from finished actions in progress['meta']."""
        actions = self.grouped_actions[group_idx]
        base_process = {
            k: self.dict[k]
            for k in (
                "orchestrator",
                "technique_name",
                "sequence_uuid",
                "experiment_uuid",
            )
        }
        base_process.update({"access": self.dict.get("access", "hte")})
        new_uuid = gen_uuid()
        base_process.update(
            {
                "process_timestamp": actions[0].time,
                "process_group_index": group_idx,
                "process_uuid": new_uuid,
                "process_name": actions[-1].name,
                "action_list": [
                    ShortActionModel(**act.dict)
                    for act in self.grouped_actions[group_idx]
                ],
            }
        )
        fill_process = {
            "action_params": self.dict["experiment_params"],
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
    def __init__(self, path: Union[HelaoPath, str], **kwargs):
        super().__init__(path, **kwargs)
        self.current_experiments = []
        self.get_experiments()
        # init again to refresh experiment list
        super().__init__(path, **kwargs)

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
        os.environ["AWS_CONFIG_FILE"] = self.config_dict["aws_config_path"]
        self.aws_session = boto3.Session(profile_name=self.config_dict["aws_profile"])
        self.s3 = self.aws_session.client("s3")
        self.bucket = self.config_dict["aws_bucket"]
        self.api_host = self.config_dict["api_host"]
        self.log_path = Path(
            os.path.join(self.base.helaodirs.states_root, "db_pending.yml")
        )
        self.log_dict = {}
        if not self.log_path.exists():
            self.log_path.write_text(
                pyaml.dump(self.log_dict, safe=True, sort_dicts=False)
            )
        else:
            self.read_log()
        if self.config_dict.get("testing", False) == True:
            self.base.print_message(
                "testing flag is True, UUIDs will be regenerated for API/S3 push.",
                info=True,
            )
            self.testing_uuid_dict = {}
        else:
            self.base.print_message(
                "testing flag is False, will use original UUIDs for API/S3 push.",
                info=True,
            )
            self.testing_uuid_dict = None
        self.loop = asyncio.get_event_loop()
        self.task_queue = asyncio.Queue()
        self.loop.create_task(self.yml_task())
        self.current_task = None
        
    async def yml_task(self):
        while True:
            yml_target = await self.task_queue.get()
            self.current_task = await self.finish_yml(yml_target)
            self.current_task = None
            self.task_queue.task_done()
        
    def read_log(self):
        yaml = YAML(typ="safe")
        self.log_dict = yaml.load(self.log_path)

    def write_log(self):
        self.log_path.write_text(pyaml.dump(self.log_dict, safe=True, sort_dicts=False))

    def update_log(self, yml_path: str, flag_dict: dict):
        if yml_path not in self.log_dict.keys():
            self.log_dict[yml_path] = {"s3": False, "api": False}
        self.log_dict[yml_path].update(flag_dict)
        self.write_log()
        if all(self.log_dict[yml_path].values()):
            self.base.print_message(f"{yml_path} is complete, removing.")
            self.rm(yml_path)

    def rm(self, yml_path: str):
        if all(self.log_dict[yml_path].values()):
            self.log_dict.pop(yml_path)
        else:
            self.base.print_message(
                f"Cannot clear {yml_path} from log when API or S3 ops are still pending.",
                info=True,
            )
        self.write_log()

    def list_pending(self):
        return self.log_dict

    async def finish_exps(self, seq_yml: SeqYml):
        seq_yml.get_experiments()
        for exp in seq_yml.current_experiments:
            if exp.status != "SYNCED":
                await self.finish_acts(exp)
                exp.parse_yml(exp.target)
                await self.finish_yml(exp.target)

    async def finish_acts(self, exp_yml: ExpYml):
        exp_yml.get_actions()
        for act in exp_yml.current_actions:
            if act.status != "SYNCED":
                await self.finish_yml(act.target)

    async def finish_pending(self):
        if len(self.log_dict) > 0:
            self.base.print_message(
                f"There are {len(self.log_dict)} ymls pending API or S3 push.",
                info=True,
            )
            yml_paths = list(self.log_dict.keys())
            for yml_path in yml_paths:
                self.base.print_message(f"Finishing {yml_path}.")
                await self.finish_yml(yml_path)
        else:
            self.base.print_message(
                "There are no ymls pending API or S3 push.", info=True
            )
        return self.log_dict

    async def add_yml_task(self, yml_path: str):
        await self.task_queue.put(yml_path)
        self.base.print_message(f"Added {yml_path} to tasks.")

    async def finish_yml(self, yml_path: Union[str, HelaoPath]):
        """Primary function for processing ymls.

        Args
        yml_path[str]: local path to yml file

        """
        if isinstance(yml_path, str):
            yml_path_str = yml_path
            hpth = HelaoPath(yml_path)
        else:
            yml_path_str = yml_path.__str__()
            hpth = yml_path
        self.base.print_message(f"Processing yml {yml_path_str}", info=True)
        if not hpth.exists():
            return f"{hpth} does not exist."
        yml_type = HelaoYml(hpth).type
        hyml = ymlmap[yml_type](hpth, uuid_test=self.testing_uuid_dict)
        ops = YmlOps(self, hyml)

        # if given a sequence or experiment, recurse through constituents
        if yml_type == YmlType.sequence:
            self.base.print_message(
                "Target yaml describes a sequence, gathering experiments.", info=True
            )
            await self.finish_exps(hyml)
            hyml.parse_yml(hyml.target)
        elif yml_type == YmlType.experiment:
            self.base.print_message(
                "Target yaml describes a experiment, gathering actions.", info=True
            )
            await self.finish_acts(hyml)
            hyml.parse_yml(hyml.target)

        # finish_yml request should be posted by orchestrator when act/exp/seq completes
        # calling this method assumes this yml and associated data are complete
        if hyml.status == "ACTIVE":
            self.base.print_message(
                "Target yaml is ACTIVE, moving to FINISHED.", info=True
            )
            ops.to_finished()

        # update progress again after finishing constituents
        if yml_type == YmlType.sequence:
            hyml.get_experiments()
        elif yml_type == YmlType.experiment:
            hyml.get_actions()

        hyml.progress.read()

        # check all 'ready', ignore all 'done'
        progress = hyml.progress
        finished = []

        # first pass, check for pending uploads
        # for pkey, pdict in progress.items():
        for pkey in progress.keys():
            if progress[pkey]["done"]:
                self.base.print_message(f"Target {pkey} is already done.", info=True)
                continue
            if progress[pkey]["ready"]:
                if progress[pkey]["pending"] or not progress[pkey]["s3"]:
                    self.base.print_message(
                        f"Target {pkey} has pending S3 push/uploads.", info=True
                    )
                    await ops.to_s3(pkey)
                    progress.read()

        for pkey in progress.keys():
            if progress[pkey]["done"]:
                self.base.print_message(f"Target {pkey} is already done.", info=True)
                continue
            if (
                len(progress[pkey]["pending"]) == 0
                and progress[pkey]["s3"]
                and not progress[pkey]["api"]
            ):
                self.base.print_message(
                    f"Target {pkey} has pending API push.", info=True
                )
                await ops.to_api(pkey)
                progress.read()

        if yml_type == YmlType.experiment:
            for pkey in [gkey for gkey in progress.keys() if isinstance(gkey, int)]:
                if progress[pkey]["done"]:
                    continue
                if progress[pkey]["ready"]:
                    if progress[pkey]["pending"] or not progress[pkey]["s3"]:
                        self.base.print_message(
                            f"Target {pkey} has pending S3 push/uploads.", info=True
                        )
                        await ops.to_s3(pkey)
                        progress.read()
                if (
                    len(progress[pkey]["pending"]) == 0
                    and progress[pkey]["s3"]
                    and not progress[pkey]["api"]
                ):
                    self.base.print_message(
                        f"Target {pkey} has pending API push.", info=True
                    )
                    await ops.to_api(pkey)
                    progress.read()

        for pkey in progress.keys():
            if progress[pkey]["done"]:
                continue
            if progress[pkey]["api"]:
                if isinstance(pkey, str):
                    ops.to_synced()
                progress[pkey].update({"done": True, "ready": False})
                progress.write()
                finished.append(pkey)
                progress.read()

        return_dict = {
            k: {dk: dv for dk, dv in d.items() if dk != "meta"}
            for k, d in progress.items()
            if k in finished
        }

        return return_dict
    
    def shutdown(self):
        self.base.print_message("Checking for queued DB tasks.")
        while not self.task_queue.empty():
            asyncio.sleep(0.2)
        self.base.print_message("All DB tasks complete. Shutting down.")
        


class YmlOps:
    def __init__(self, dbp: DBPack, yml: Union[ActYml, ExpYml, SeqYml]):
        self.dbp = dbp
        self.yml = yml

    async def to_api(self, progress_key: Union[str, int], retry_num: int = 2):
        """Submit to modelyst DB"""
        # init global log

        # no pending files, yml pushed to S3
        pdict = self.yml.progress[progress_key]
        if pdict["pending"] or not pdict["s3"]:
            self.dbp.base.print_message("Cannot push to API with S3 upload pending.")
            return ErrorCodes.not_allowed
        meta_type = pdict["type"]
        if meta_type == "experiment":
            # don't push to API until all actions are done (check current_actions)
            if not all(
                [
                    act_yml.progress[act_yml.pkey]["done"]
                    for act_yml in self.yml.current_actions
                ]
            ):
                return False
        elif meta_type == "sequence":
            # don't push to API until all experiments are done (check current_experiments)
            if not all(
                [
                    exp_yml.progress[exp_yml.pkey]["done"]
                    for exp_yml in self.yml.current_experiments
                ]
            ):
                return False
        p_uuid = pdict["meta"][
            f"{meta_type}_uuid" if isinstance(progress_key, str) else "process_uuid"
        ]
        req_model = modmap[meta_type](**pdict["meta"]).json_dict()
        req_url = f"https://{self.dbp.api_host}/{plural[meta_type]}/"
        self.dbp.base.print_message(
            f"attempting API push for {self.yml.target.__str__()} :: {progress_key} :: {p_uuid}"
        )
        try_create = True
        last_response = {}
        async with aiohttp.ClientSession() as session:
            for i in range(retry_num):
                if not pdict["api"]:
                    req_method = session.post if try_create else session.patch
                    api_str = f"API {'POST' if try_create else 'PATCH'}"
                    async with req_method(req_url, json=req_model) as resp:
                        if resp.status == 200:
                            pdict["api"] = True
                            self.yml.progress.write()
                        elif resp.status == 400:
                            try_create = False
                        self.dbp.base.print_message(
                            f"[{i+1}/{retry_num}] {api_str} {p_uuid} returned status: {resp.status}"
                        )
                        last_response = await resp.json()
                        self.dbp.base.print_message(
                            f"[{i+1}/{retry_num}] {api_str} {p_uuid} response: {last_response}"
                        )
                    await asyncio.sleep(1)

        if pdict["api"]:
            self.dbp.base.print_message(f"{api_str} {p_uuid} success")
            if isinstance(progress_key, str):
                self.dbp.update_log(self.yml.target.__str__(), {"api": True})
            return ErrorCodes.none
        else:
            self.dbp.base.print_message(
                f"Did not post {p_uuid} after {retry_num} tries."
            )
            # send yml and response status to API endpoint if failure.
            meta_s3_key = f"{meta_type}/{p_uuid}.json"
            fail_model = {
                "endpoint": f"https://{self.dbp.api_host}/{plural[meta_type]}/",
                "method": "POST" if try_create else "PATCH",
                "status_code": resp.status,
                "detail": last_response.get('detail', ''),
                "data": req_model,
                "s3_files": [
                    {
                        "bucket_name": self.dbp.bucket,
                        "key": meta_s3_key,
                    }
                ],
            }
            fail_url = f"https://{self.dbp.api_host}/failed"
            self.dbp.base.print_message(
                f"attempting API push for failed {self.yml.target.__str__()} :: {progress_key} :: {p_uuid}"
            )
            async with aiohttp.ClientSession() as session:
                for i in range(retry_num):
                    async with session.post(fail_url, json=fail_model) as resp:
                        if resp.status == 200:
                            self.dbp.base.print_message(
                                f"successful API push for failed {self.yml.target.__str__()} :: {progress_key} :: {p_uuid}"
                            )
                        else:
                            self.dbp.base.print_message(
                                f"failed API push for failed {self.yml.target.__str__()} :: {progress_key} :: {p_uuid}"
                            )
                            self.dbp.base.print_message(
                                f"response: {await resp.json()}"
                            )
            if isinstance(progress_key, str):
                self.dbp.update_log(self.yml.target.__str__(), {"api": False})
            return ErrorCodes.http

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
                tb = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
                self.dbp.base.print_message(e)
                self.dbp.base.print_message(
                    f"Retry S3 upload [{i}/{retry_num}]: {self.dbp.bucket}, {target}"
                )
                await asyncio.sleep(1)
        self.dbp.base.print_message(f"Did not upload {target} after {retry_num} tries.")
        return False

    async def to_s3(self, progress_key: Union[str, int], retry_num: int = 2):
        """Upload data_files and yml/json to S3"""

        pdict = self.yml.progress[progress_key]
        if isinstance(progress_key, int):  # process group
            meta_type = "process"
        else:
            meta_type = self.yml.type.lower()
        meta_type = pdict["type"]
        p_uuid = pdict["meta"][
            f"{meta_type}_uuid" if isinstance(progress_key, str) else "process_uuid"
        ]

        hlo_data = [x for x in pdict["pending"] if x.endswith(".hlo")]
        for fpath in hlo_data:
            file_s3_key = f"raw_data/{p_uuid}/{os.path.basename(fpath)}.json"
            file_meta, file_data = read_hlo(fpath)
            file_json = {"meta": file_meta, "data": file_data}
            self.dbp.base.print_message(f"attempting S3 push for {file_s3_key}")
            file_success = await self._to_s3(file_json, file_s3_key, retry_num)
            if file_success:
                pdict["pending"].remove(fpath)
                self.yml.progress[progress_key].update(pdict)
                self.yml.progress.write()
                pdict["pushed"].update({os.path.basename(fpath): datetime.now()})
                self.yml.progress[progress_key].update(pdict)
                self.yml.progress.write()

        aux_data = [x for x in pdict["pending"] if not x.endswith(".hlo")]
        for fpath in aux_data:
            file_s3_key = f"raw_data/{p_uuid}/{os.path.basename(fpath)}.json"
            self.dbp.base.print_message(f"attempting S3 push for {file_s3_key}")
            file_success = await self._to_s3(fpath, file_s3_key, retry_num)
            if file_success:
                pdict["pending"].remove(fpath)
                self.yml.progress[progress_key].update(pdict)
                self.yml.progress.write()
                pdict["pushed"].update({os.path.basename(fpath): datetime.now()})
                self.yml.progress[progress_key].update(pdict)
                self.yml.progress.write()

        if not pdict["s3"]:
            meta_s3_key = f"{meta_type}/{p_uuid}.json"
            self.dbp.base.print_message(f"attempting S3 push for {meta_s3_key}")
            meta_model = pdict["meta"]
            if meta_type == "experiment":
                process_keys = sorted(
                    [k for k in self.yml.progress.keys() if isinstance(k, int)]
                )
                process_list = [
                    self.yml.progress[pk]["meta"]["process_uuid"] for pk in process_keys
                ]
                meta_model["process_list"] = process_list
            meta_success = await self._to_s3(meta_model, meta_s3_key, retry_num)
            if meta_success:
                pdict["s3"] = True
                self.yml.progress[progress_key].update(pdict)
                self.yml.progress.write()
        if isinstance(progress_key, str):
            if pdict["s3"] and len(pdict["pending"]) == 0:
                self.dbp.update_log(self.yml.target.__str__(), {"s3": True})
            else:
                self.dbp.update_log(self.yml.target.__str__(), {"s3": False})

    def to_finished(self):
        """Moves yml and data folder from ACTIVE to FINISHED path."""
        if self.yml.status == "ACTIVE":
            for file_path in self.yml.data_files:
                file_path.finished.parent.mkdir(parents=True, exist_ok=True)
                self.dbp.base.print_message(f"moving {file_path.__str__()} to FINISHED")
                move_success = False
                while move_success == False:
                    try:
                        file_path.replace(file_path.finished)
                        move_success = True
                    except PermissionError:
                        self.dbp.base.print_message(f"{file_path} is in use, retrying.")
                        sleep(1)
            self.yml.target.finished.parent.mkdir(parents=True, exist_ok=True)
            self.dbp.base.print_message(
                f"moving {self.yml.target.__str__()} to FINISHED"
            )
            new_target = self.yml.target.replace(self.yml.target.finished)
            self.dbp.base.print_message(f"cleaning up {self.yml.target.__str__()}")
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
            for file_path in self.yml.data_files:
                file_path.synced.parent.mkdir(parents=True, exist_ok=True)
                self.dbp.base.print_message(f"moving {file_path.__str__()} to SYNCED")
                move_success = False
                while move_success == False:
                    try:
                        file_path.replace(file_path.synced)
                        move_success = True
                    except PermissionError:
                        self.dbp.base.print_message(f"{file_path} is in use, retrying.")
                        sleep(1)
            self.yml.target.synced.parent.mkdir(parents=True, exist_ok=True)
            self.dbp.base.print_message(f"moving {self.yml.target.__str__()} to SYNCED")
            new_target = self.yml.target.replace(self.yml.target.synced)
            self.dbp.base.print_message(f"cleaning up {self.yml.target.__str__()}")
            clean_success = self.yml.target.cleanup()
            if clean_success != "success":
                self.dbp.base.print_message("Could not clean directory after moving.")
                self.dbp.base.print_message(clean_success)
            self.yml.parse_yml(new_target)
