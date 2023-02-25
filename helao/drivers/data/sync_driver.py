"""Data sync driver

Handles Helao data and metadata uploads to S3 and Modelyst API.

0. Only .ymls in RUNS_FINISHED may sync
1. Every .yml maps to a .progress file in RUNS_SYNCED
2. Experiment .ymls track actions, Sequence .ymls track experiments
3. Process .ymls are created alongside experiment .progress
4. Actions w/process_finish will trigger process .yml creation
5. Progress is written after S3 and API actions, and initial load
6. Progress is kept in memory until parent has synced
7. Progress may be loaded into memory, but don't recursively load actions

"""

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
from typing import Union, Optional, Dict, List
from collections import UserDict, defaultdict
import traceback

import pyaml
import botocore.exceptions
import boto3
import aiohttp
from helaocore.error import ErrorCodes
from helao.servers.base import Base
from helaocore.models.process import ProcessModel
from helaocore.models.action import ShortActionModel, ActionModel
from helaocore.models.experiment import ExperimentModel
from helaocore.models.sequence import SequenceModel
from helao.helpers.gen_uuid import gen_uuid
from helao.helpers.read_hlo import read_hlo
from helao.helpers.print_message import print_message
from helao.helpers.zip_dir import zip_dir
from helao.drivers.data.enum import YmlType

ABR_MAP = {"act": "action", "exp": "experiment", "seq": "sequence"}
MOD_MAP = {
    "action": ActionModel,
    "experiment": ExperimentModel,
    "sequence": SequenceModel,
    "process": ProcessModel,
}
PLURALS = {
    "action": "actions",
    "experiment": "experiments",
    "sequence": "sequences",
    "process": "processes",
}
YAML_LOADER = YAML(typ="safe")
MAX_TASKS = 4


def dict2json(input_dict: dict):
    """Converts dict to file-like object containing json."""
    bio = io.BytesIO()
    StreamWriter = codecs.getwriter("utf-8")
    wrapper_file = StreamWriter(bio)
    json.dump(input_dict, wrapper_file)
    bio.seek(0)
    return bio


class HelaoYml:
    target: Path
    dir: Path
    parts: list

    def __init__(self, target: Union[Path, str]):
        if isinstance(target, str):
            self.target = Path(target)
        else:
            self.target = target
        self.parts = list(Path(target).parts)
        self.check_paths()

    def check_paths(self):
        if not self.exists:
            for p in (self.active_path, self.finished_path, self.synced_path):
                self.target = p
                if self.exists:
                    break
            if not self.exists:
                raise ValueError(f"{self.target} does not exist")
        else:
            if self.target.is_dir():
                self.dir = self.target
                possible_ymls = [
                    x
                    for x in list(self.dir.glob("*.yml"))
                    if x.stem.endswith("-seq")
                    or x.stem.endswith("-exp")
                    or x.stem.endswith("-act")
                ]
                if len(possible_ymls) > 1:
                    raise ValueError(
                        f"{self.dir} contains multiple .yml files and is not a valid Helao directory"
                    )
                elif not possible_ymls:
                    raise ValueError(
                        f"{self.dir} does not contain any .yml files and is not a valid Helao dir"
                    )
                self.target = possible_ymls[0]
            else:
                self.dir = self.target.parent
        self.parts = list(self.target.parts)
        if not any([x.startswith("RUNS_") for x in self.dir.parts]):
            raise ValueError(
                f"{self.target} is not located with a Helao RUNS_* directory"
            )

    @property
    def exists(self):
        return self.target.exists()

    def __repr__(self):
        return f"{self.type[:3].upper()}: {self.target.parent.name} ({self.status})"

    @property
    def type(self):
        return ABR_MAP[self.target.stem.split("-")[-1]]

    @property
    def timestamp(self):
        ts = datetime.strptime(self.target.stem.split("-")[0], "%Y%m%d.%H%M%S%f")
        return ts

    @property
    def status(self):
        path_parts = [x for x in self.dir.parts if x.startswith("RUNS_")]
        status = path_parts[0].split("_")[-1].lower()
        return status

    def rename(self, status: str) -> str:
        tempparts = list(self.parts)
        tempparts[self.status_idx] = status
        return os.path.join(*tempparts)

    @property
    def status_idx(self):
        valid_statuses = ("RUNS_ACTIVE", "RUNS_FINISHED", "RUNS_SYNCED")
        return [any([x in valid_statuses]) for x in self.parts].index(True)

    @property
    def relative_path(self):
        return "/".join(list(self.parts)[self.status_idx + 1 :])

    @property
    def active_path(self):
        return Path(self.rename("RUNS_ACTIVE"))

    @property
    def finished_path(self):
        return Path(self.rename("RUNS_FINISHED"))

    @property
    def synced_path(self):
        return Path(self.rename("RUNS_SYNCED"))

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
                _ = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                return e

    def list_children(self, yml_path: Path):
        paths = yml_path.parent.glob("*/*.yml")
        hpaths = [HelaoYml(x) for x in paths]
        return sorted(hpaths, key=lambda x: x.timestamp)

    @property
    def active_children(self) -> list:
        return self.list_children(self.active_path)

    @property
    def finished_children(self) -> list:
        return self.list_children(self.finished_path)

    @property
    def synced_children(self) -> list:
        return self.list_children(self.synced_path)

    @property
    def children(self) -> list:
        all_children = (
            self.active_children + self.finished_children + self.synced_children
        )
        return sorted(all_children, key=lambda x: x.timestamp)

    @property
    def misc_files(self) -> List[Path]:
        return [
            x
            for x in self.dir.glob("*")
            if x.is_file() and not x.suffix == ".yml" and not x.suffix == ".hlo"
        ]

    @property
    def hlo_files(self) -> List[Path]:
        return [x for x in self.dir.glob("*") if x.is_file() and x.suffix == ".hlo"]

    @property
    def parent_path(self) -> Path:
        if self.type == "sequence":
            return self.target
        else:
            possible_parents = [
                list(x.parent.parent.glob("*.yml"))
                for x in (self.active_path, self.finished_path, self.synced_path)
            ]
            return [p[0] for p in possible_parents if p][0]

    @property
    def meta(self):
        return YAML_LOADER.load(self.target)

    def write_meta(self, meta_dict: dict):
        self.target.write_text(str(pyaml.dump(meta_dict, safe=True, sort_dicts=False)))


class Progress:
    yml: HelaoYml
    prg: Path

    def __init__(self, path: Union[HelaoYml, Path, str]):
        """Loads and saves progress for a given Helao yml or prg file."""

        if isinstance(path, HelaoYml):
            self.yml = path
        elif isinstance(path, Path):
            if path.suffix == ".yml":
                self.yml = HelaoYml(path)
            elif path.suffix == ".prg":
                self.prg = path
        else:
            if path.endswith(".yml"):
                self.yml = HelaoYml(path)
            elif path.endswith(".prg"):
                self.prg = Path(path)
            else:
                raise ValueError(f"{path} is not a valid Helao .yml or .prg file")

        if not hasattr(self, "yml"):
            self.read_dict()
            self.yml = HelaoYml(self.dict["yml"])

        if not hasattr(self, "prg"):
            self.prg = self.yml.synced_path.with_suffix(".prg")

        # first time, write progress dict
        if not self.prg.exists():
            self.prg.parent.mkdir(parents=True, exist_ok=True)
            self.dict = {
                "yml": self.yml.target.__str__(),
                "api": False,
                "s3": False,
            }
            if self.yml.type == "action":
                act_dict = {
                    "files_pending": [],
                    "files_s3": {},
                }
                self.dict.update(act_dict)
            if self.yml.type == "experiment":
                exp_dict = {
                    "process_finishers": [],  # final action indices
                    "process_contribs": {},
                    "process_metas": {},
                    "process_s3": {},
                    "process_api": {},
                }
                self.dict.update(exp_dict)
            self.write_dict()
        elif not hasattr(self, "dict"):
            self.read_dict()

    def read_dict(self):
        self.dict = YAML_LOADER.load(self.prg)

    def write_dict(self, new_dict: Optional[dict] = None):
        if new_dict is None:
            self.prg.write_text(str(pyaml.dump(self.dict, safe=True, sort_dicts=False)))
        else:
            self.prg.write_text(str(pyaml.dump(new_dict, safe=True, sort_dicts=False)))

    @property
    def s3_done(self):
        return self.dict["s3"]

    @property
    def api_done(self):
        return self.dict["api"]

    def remove_prg(self):
        self.prg.unlink()


class HelaoSyncer:
    progress: Dict[str, Progress]
    base: Base
    running_tasks: dict

    def __init__(self, action_serv: Base):
        """Pushes yml to S3 and API."""
        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.world_config = action_serv.world_cfg
        os.environ["AWS_CONFIG_FILE"] = self.config_dict["aws_config_path"]
        self.aws_session = boto3.Session(profile_name=self.config_dict["aws_profile"])
        self.s3 = self.aws_session.client("s3")
        self.bucket = self.config_dict["aws_bucket"]
        self.api_host = self.config_dict["api_host"]

        self.progress = {}
        self.task_queue = asyncio.PriorityQueue()
        self.running_tasks = {}
        # push happens via async task queue
        # processes are checked after each action push
        # pushing an exp before processes/actions have synced will first enqueue actions
        # then enqueue processes, then enqueue the exp again
        # exp progress must be in memory before actions are checked

        self.syncer_loop = asyncio.create_task(self.syncer())
        pass

    async def syncer(self):
        """Syncer loop coroutine which consumes the task queue."""
        while True:
            if len(self.running_tasks) < MAX_TASKS:
                _, yml_target = await self.task_queue.get()
                if yml_target.name not in self.running_tasks:
                    task = asyncio.create_task(self.sync_yml(yml_target))
                    self.running_tasks[yml_target.name]
                    task.add_done_callback(self.running_tasks.pop(yml_target.name))
            else:
                await asyncio.sleep(0.1)

    def get_progress(self, yml_path: Path):
        if yml_path.name in self.progress:
            prog = self.progress[yml_path.name]
            if not prog.yml.exists:
                prog.yml.check_paths()
                prog.dict.update({"yml": prog.yml.target.__str__()})
                prog.write_dict()
        else:
            prog = Progress(yml_path)
            self.progress[yml_path.name] = prog
        return prog

    async def enqueue_yml(self, upath: Union[Path, str], rank: int = 2):
        yml_path = Path(upath) if isinstance(upath, str) else upath
        await self.task_queue.put((rank, yml_path))

    async def sync_yml(self, yml_path: Path):
        """Coroutine for syncing a single yml"""
        prog = self.get_progress(yml_path)
        yml = prog.yml
        meta = yml.meta

        if yml.status == "synced":
            self.base.print_message(
                f"Cannot sync {yml.target.__str__()}, status is already 'synced'."
            )
            return True

        if yml.status != "finished":
            self.base.print_message(
                f"Cannot sync {yml.target.__str__()}, status is not 'finished'."
            )
            return False

        # first check if child objects are registered with API (non-actions)
        if yml.type != "action":
            if yml.active_children:
                self.base.print_message(
                    f"Cannot sync {yml.target.__str__()}, children are still 'active'."
                )
                return False
            if yml.finished_children:
                self.base.print_message(
                    f"Cannot sync {yml.target.__str__()}, children are not 'synced'."
                )
                self.base.print_message(
                    "Adding 'finished' children to sync queue with highest priority."
                )
                for child in yml.finished_children:
                    await self.enqueue_yml(child.target, 0)
                    self.base.print_message(child.target.__str__())
                self.base.print_message(
                    f"Re-adding {yml.target.__str__()} to sync queue with high priority."
                )
                await self.enqueue_yml(yml.target, 1)
                return False

        # next push files to S3 (actions only)
        if yml.type == "action":
            # check for process_contribs
            exp_path = Path(yml.parent_path)
            exp_prog = self.get_progress(exp_path)
            exp_yml = exp_prog.yml

            # re-check file lists
            prog.dict["files_pending"] += [
                p
                for p in yml.hlo_files + yml.misc_files
                if p not in prog.dict["files_pending"]
                and p not in prog.dict["files_s3"]
            ]
            # push files to S3
            for p in prog.dict["files_pending"]:
                if p.suffix == ".hlo":
                    file_s3_key = f"raw_data/{meta['action_uuid']}/{p.name}.json"
                    file_meta, file_data = read_hlo(p.__str__())
                    msg = {"meta": file_meta, "data": file_data}
                else:
                    file_s3_key = f"raw_data/{meta['action_uuid']}/{p.name}"
                    msg = p
                file_success = await self.to_s3(msg, file_s3_key)
                if file_success:
                    prog.dict["files_pending"].remove(p)
                    prog.dict["files_s3"].update({p.name: file_s3_key})
                    prog.write_dict()

        # if yml is an experiment check processes

        # next push yml to S3
        if not prog.s3_done:
            uuid_key = meta[f"{yml.type}_uuid"]
            meta_s3_key = f"{yml.type}/{uuid_key}.json"
            meta_success = await self.to_s3(meta, meta_s3_key)
            if meta_success:
                prog.dict["s3"] = True
                prog.write_dict()

        # next push yml to API

        # if yml is action and there are process contribs, update experiment progress

    async def to_s3(self, msg: Union[dict, Path], target: str, retries: int = 3):
        if isinstance(msg, dict):
            uploaded = dict2json(msg)
            uploader = self.s3.upload_fileobj
        else:
            uploaded = msg.__str__()
            uploader = self.s3.upload_file
        for i in range(retries + 1):
            if i > 0:
                self.base.print_message(
                    f"S3 retry [{i}/{retries}]: {self.bucket}, {target}"
                )
            try:
                uploader(uploaded, self.bucket, target)
                return True
            except botocore.exceptions.ClientError as e:
                _ = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                self.base.print_message(e)
                await asyncio.sleep(1)
        self.base.print_message(f"Did not upload {target} after {retries} tries.")
        return False
