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

__all__ = ["HelaoYml", "Progress", "HelaoSyncer"]

import os
import shutil
import io
import codecs
import json
import asyncio
from zipfile import ZipFile
from pathlib import Path
from datetime import datetime
from typing import Union, Optional, Dict, List
import traceback
from collections import defaultdict
from copy import copy

import botocore.exceptions
import boto3
import gzip

# from filelock import FileLock

from helao.servers.base import Base
from helaocore.models.process import ProcessModel
from helaocore.models.action import ShortActionModel, ActionModel
from helaocore.models.experiment import ExperimentModel
from helaocore.models.sequence import SequenceModel
from helao.helpers.gen_uuid import gen_uuid
from helao.helpers.read_hlo import read_hlo
from helao.helpers.yml_tools import yml_dumps, yml_load
from helao.helpers.zip_dir import zip_dir

from helao.helpers import logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(logger_name="sync_driver_standalone")
else:
    LOGGER = logging.LOGGER

from time import sleep
from glob import glob
import aiohttp

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
MOD_PATCH = {
    "exid": "exec_id",
}


def dict2json(input_dict: dict):
    """Converts dict to file-like object containing json."""
    bio = io.BytesIO()
    stream_writer = codecs.getwriter("utf-8")
    wrapper_file = stream_writer(bio)
    json.dump(input_dict, wrapper_file)
    bio.seek(0)
    return bio


def move_to_synced(file_path: Path):
    """Moves item from RUNS_FINISHED to RUNS_SYNCED."""
    parts = list(file_path.parts)
    state_index = parts.index("RUNS_FINISHED")
    parts[state_index] = "RUNS_SYNCED"
    target_path = Path(*parts)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        new_path = file_path.replace(target_path)
        return new_path
    except PermissionError:
        print(f"Permission error when moving {file_path} to {target_path}")
        return False


def revert_to_finished(file_path: Path):
    """Moves item from RUNS_SYNCED to RUNS_FINISHED."""
    parts = list(file_path.parts)
    state_index = parts.index("RUNS_SYNCED")
    parts[state_index] = "RUNS_FINISHED"
    target_path = Path(*parts)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        new_path = file_path.replace(target_path)
        return new_path
    except PermissionError:
        print(f"Permission error when moving {file_path} to {target_path}")
        return False


class HelaoYml:
    target: Path
    targetdir: Path

    def __init__(self, target: Union[Path, str]):
        if isinstance(target, str):
            self.target = Path(target)
        else:
            self.target = target
        self.check_paths()
        # self.filelockpath = str(self.target) + ".lock"
        # self.filelock = FileLock(self.filelockpath)
        # if not os.path.exists(self.filelockpath):
        #     os.makedirs(os.path.dirname(self.filelockpath), exist_ok=True)
        #     with open(self.filelockpath, "w") as _:
        #         pass
        # with self.filelock:
        #     self.meta = yml_load(self.target)
        self.meta = yml_load(self.target)

    @property
    def parts(self):
        return list(self.target.parts)

    def check_paths(self):
        if not self.exists:
            for p in (self.active_path, self.finished_path, self.synced_path):
                self.target = p
                if self.exists:
                    break
            if not self.exists:
                print(f"{self.target} does not exist")
        if self.target.is_dir():
            self.targetdir = self.target
            possible_ymls = [
                x
                for x in list(self.targetdir.glob("*.yml"))
                if x.stem.endswith("-seq")
                or x.stem.endswith("-exp")
                or x.stem.endswith("-act")
            ]
            if len(possible_ymls) > 1:
                raise ValueError(
                    f"{self.targetdir} contains multiple .yml files and is not a valid Helao directory"
                )
            elif not possible_ymls:
                raise ValueError(
                    f"{self.targetdir} does not contain any .yml files and is not a valid Helao dir"
                )
            self.target = possible_ymls[0]
        else:
            self.targetdir = self.target.parent
        # self.parts = list(self.target.parts)
        if not any([x.startswith("RUNS_") for x in self.targetdir.parts]):
            raise ValueError(
                f"{self.target} is not located with a Helao RUNS_* directory"
            )
        # self.filelockpath = str(self.target) + ".lock"
        # self.filelock = FileLock(self.filelockpath)

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
        path_parts = [x for x in self.targetdir.parts if x.startswith("RUNS_")]
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
        if not self.target.exists() or self.target == self.synced_path:
            return "success"
        tempparts = list(self.parts)
        steps = len(tempparts) - self.status_idx
        for i in range(1, steps):
            check_dir = Path(os.path.join(*tempparts[:-i]))
            contents = [x for x in check_dir.glob("*") if x != check_dir]
            if contents:
                print(f"{str(check_dir)} is not empty")
                print(contents)
                return "failed"
            try:
                check_dir.rmdir()
            except PermissionError as err:
                str_err = "".join(
                    traceback.format_exception(type(err), err, err.__traceback__)
                )
                return str_err
        return "success"

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
            for x in self.targetdir.glob("*")
            if x.is_file()
            and not x.suffix == ".yml"
            and not x.suffix == ".hlo"
            and not x.suffix == ".lock"
        ]

    @property
    def lock_files(self) -> List[Path]:
        return [
            x for x in self.targetdir.glob("*") if x.is_file() and x.suffix == ".lock"
        ]

    @property
    def hlo_files(self) -> List[Path]:
        return [
            x for x in self.targetdir.glob("*") if x.is_file() and x.suffix == ".hlo"
        ]

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

    # @property
    # def meta(self):
    #     with self.filelock:
    #         ymld = yml_load(self.target)
    #     return ymld

    def write_meta(self, meta_dict: dict):
        # with self.filelock:
        self.target.write_text(
            str(
                yml_dumps(meta_dict),
                encoding="utf-8",
            )
        )


class Progress:
    ymlpath: HelaoYml
    prg: Path
    dict: Dict

    def __init__(self, path: Union[Path, str]):
        """Loads and saves progress for a given Helao yml or prg file."""

        if isinstance(path, Path):
            if path.suffix == ".yml":
                self.ymlpath = path
            elif path.suffix == ".prg":
                self.prg = path
        else:
            if path.endswith(".yml"):
                self.ymlpath = Path(path)
            elif path.endswith(".prg"):
                self.prg = Path(path)
            else:
                raise ValueError(f"{path} is not a valid Helao .yml or .prg file")

        # if not hasattr(self, "yml"):
        #     self.read_dict()
        #     self.yml = HelaoYml(self.dict["yml"])

        if not hasattr(self, "prg"):
            self.prg = self.yml.synced_path.with_suffix(".prg")

        # self.prglockpath = str(self.prg) + ".lock"
        # self.prglock = FileLock(self.prglockpath)
        # if not os.path.exists(self.prglockpath):
        #     os.makedirs(os.path.dirname(self.prglockpath), exist_ok=True)
        #     with open(self.prglockpath, "w") as _:
        #         pass

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
                process_groups = self.yml.meta.get("process_order_groups", {})
                exp_dict = {
                    "process_actions_done": {},  # {action submit order: yml.target.name}
                    "process_groups": process_groups,  # {process_idx: contributor action indices}
                    "process_metas": {},  # {process_idx: yml_dict}
                    "process_s3": [],  # list of process_idx with S3 done
                    "process_api": [],  # list of process_idx with API done
                    "legacy_finisher_idxs": [],  # end action indicies (submit order)
                    "legacy_experiment": False if process_groups else True,
                }
                self.dict.update(exp_dict)
            self.write_dict()
        else:
            self.read_dict()

    @property
    def yml(self):
        return HelaoYml(self.ymlpath)

    def list_unfinished_procs(self):
        """Returns pair of lists with non-synced s3 and api processes."""
        if self.yml.type == "experiment":
            s3_unf = [
                x
                for x in self.dict["process_groups"].keys()
                if x not in self.dict["process_s3"]
            ]
            api_unf = [
                x
                for x in self.dict["process_groups"].keys()
                if x not in self.dict["process_api"]
            ]
            return s3_unf, api_unf
        return [], []

    def read_dict(self):
        self.dict = yml_load(self.prg)

    def write_dict(self, new_dict: Optional[Dict] = None):
        out_dict = self.dict if new_dict is None else new_dict
        # with self.prglock:
        self.prg.write_text(str(yml_dumps(out_dict)), encoding="utf-8")

    @property
    def s3_done(self):
        return self.dict["s3"]

    @property
    def api_done(self):
        return self.dict["api"]

    def remove_prg(self):
        # with self.prglock:
        self.prg.unlink()


class HelaoSyncer:
    progress: Dict[str, Progress]
    base: Base
    running_tasks: dict

    def __init__(self, action_serv: Base, db_server_name: str = "DB"):
        """Pushes yml to S3 and API."""
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.world_config = action_serv.world_cfg
        self.max_tasks = self.config_dict.get("max_tasks", 8)
        # to load this driver on orch, we check the default "DB" key or take a manually-specified key
        if (
            not self.config_dict.get("aws_config_path", False)
            and db_server_name in self.world_config["servers"]
        ):
            self.config_dict = self.world_config["servers"][db_server_name].get(
                "params", {}
            )
        if "aws_config_path" in self.config_dict:
            os.environ["AWS_CONFIG_FILE"] = self.config_dict["aws_config_path"]
            self.aws_session = boto3.Session(
                profile_name=self.config_dict["aws_profile"]
            )
            self.s3 = self.aws_session.client("s3")
        else:
            self.aws_session = None
            self.s3 = None
        self.bucket = self.config_dict["aws_bucket"]
        self.api_host = self.config_dict["api_host"]

        # self.progress = {}
        self.sequence_objs = {}
        self.task_queue = asyncio.PriorityQueue()
        # self.task_set = set()
        self.running_tasks = {}
        self.aiolock = asyncio.Lock()
        # push happens via async task queue
        # processes are checked after each action push
        # pushing an exp before processes/actions have synced will first enqueue actions
        # then enqueue processes, then enqueue the exp again
        # exp progress must be in memory before actions are checked

        self.syncer_loop = asyncio.create_task(self.syncer(), name="syncer_loop")

    def try_remove_empty(self, remove_target):
        success = False
        contents = glob(os.path.join(remove_target, "*"))
        if len(contents) == 0:
            try:
                os.rmdir(remove_target)
                success = True
            except Exception as err:
                tb = "".join(
                    traceback.format_exception(type(err), err, err.__traceback__)
                )
                self.base.print_message(
                    f"Directory {remove_target} is empty, but could not removed. {repr(err), tb,}",
                    error=True,
                )
        else:
            sub_dirs = [x for x in contents if os.path.isdir(x)]
            sub_success = False
            sub_removes = []
            for subdir in sub_dirs:
                sub_removes.append(self.try_remove_empty(subdir))
            sub_success = all(sub_removes)
            sub_files = [x for x in contents if os.path.isfile(x)]
            if not sub_files and sub_success:
                success = True
        return success

    def cleanup_root(self):
        """Remove leftover empty directories."""
        today = datetime.strptime(datetime.now().strftime("%Y%m%d"), "%Y%m%d")
        chkdirs = ["RUNS_ACTIVE", "RUNS_FINISHED"]
        for cd in chkdirs:
            seq_dates = glob(os.path.join(self.world_config["root"], cd, "*", "*"))
            for datedir in seq_dates:
                try:
                    dateonly = datetime.strptime(os.path.basename(datedir), "%Y%m%d")
                except ValueError:
                    dateonly = datetime.strptime(
                        os.path.basename(datedir), "%Y%m%d.%H%M%S%f"
                    )
                if dateonly <= today:
                    seq_dirs = glob(os.path.join(datedir, "*"))
                    if len(seq_dirs) == 0:
                        self.try_remove_empty(datedir)
                    weekdir = os.path.dirname(datedir)
                    if len(glob(os.path.join(weekdir, "*"))) == 0:
                        self.try_remove_empty(weekdir)

    def sync_exit_callback(self, task: asyncio.Task):
        task_name = task.get_name()
        if task_name in self.running_tasks:
            # self.base.print_message(f"Removing {task_name} from running_tasks.")
            self.running_tasks.pop(task_name)
        # else:
        #     self.base.print_message(
        #         f"{task_name} was already removed from running_tasks."
        #     )

    async def syncer(self):
        """Syncer loop coroutine which consumes the task queue."""
        while True:
            if len(self.running_tasks) < self.max_tasks:
                # self.base.print_message("Getting next yml_target from queue.")
                rank, yml_path = await self.task_queue.get()
                # self.task_set.remove(yml_path.name)
                # self.base.print_message(
                #     f"Acquired {yml_target.name} with priority {rank}."
                # )
                if yml_path.name not in self.running_tasks:
                    # self.base.print_message(
                    #     f"Creating sync task for {yml_target.name}."
                    # )
                    self.running_tasks[yml_path.name] = asyncio.create_task(
                        self.sync_yml(yml_path=yml_path, rank=rank),
                        name=yml_path.name,
                    )
                    self.running_tasks[yml_path.name].add_done_callback(
                        self.sync_exit_callback
                    )
                # else:
                #     print_message(f"{yml_target} sync is already in progress.")
            await asyncio.sleep(0.1)

    def get_progress(self, yml_path: Path):
        """Returns progress from global dict, updates yml_path if yml path not found."""
        # ymllockpath = str(yml_path) + ".lock"
        # if not os.path.exists(ymllockpath):
        #     os.makedirs(os.path.dirname(ymllockpath), exist_ok=True)
        #     with open(ymllockpath, "w") as _:
        #         pass
        # ymllock = FileLock(ymllockpath)
        # with ymllock:
        # if yml_path.name in self.progress:
        #     prog = self.progress[yml_path.name]
        #     if not prog.yml.exists:
        #         prog.yml.check_paths()
        #         prog.dict.update({"yml": str(prog.yml.target)})
        #         prog.write_dict()
        # else:
        if not yml_path.exists():
            hy = HelaoYml(yml_path)
            hy.check_paths()
            prog = Progress(hy.target)
            prog.write_dict()
        else:
            prog = Progress(yml_path)
        # self.progress[yml_path.name] = prog
        # return self.progress[yml_path.name]
        return prog

    async def enqueue_yml(
        self, upath: Union[Path, str], rank: int = 5, rank_limit: int = -5
    ):
        """Adds yml to sync queue, defaulting to lowest priority."""
        yml_path = Path(upath) if isinstance(upath, str) else upath
        if rank < rank_limit:
            self.base.print_message(
                f"{str(yml_path)} re-queue rank is under {rank_limit}, skipping enqueue request."
            )
        # elif yml_path.name in self.task_set:
        #     self.base.print_message(
        #         f"{str(yml_path)} is already queued, skipping enqueue request."
        #     )
        elif yml_path.name in self.running_tasks:
            self.base.print_message(
                f"{str(yml_path)} is already running, skipping enqueue request."
            )
        else:
            # self.task_set.add(yml_path.name)
            await self.task_queue.put((rank, yml_path))
            LOGGER.info(f"Added {str(yml_path)} to syncer queue with priority {rank}.")

    async def sync_yml(
        self,
        yml_path: Path,
        retries: int = 3,
        rank: int = 5,
        force_s3: bool = False,
        force_api: bool = False,
    ):
        """Coroutine for syncing a single yml"""
        if not yml_path.exists():
            # self.base.print_message(
            #     f"{str(yml_path)} does not exist, assume yml has moved to synced."
            # )
            return True
        prog = self.get_progress(yml_path)
        if not prog:
            # self.base.print_message(
            #     f"{str(yml_path)} does not exist, assume yml has moved to synced."
            # )
            return True

        meta = copy(prog.yml.meta)

        if prog.yml.status == "synced":
            # self.base.print_message(
            #     f"Cannot sync {str(prog.yml.target)}, status is already 'synced'."
            # )
            return True

        # self.base.print_message(
        #     f"{str(prog.yml.target)} status is not synced, checking for finished."
        # )

        if prog.yml.status == "active":
            # self.base.print_message(
            #     f"Cannot sync {str(prog.yml.target)}, status is not 'finished'."
            # )
            return False

        # self.base.print_message(f"{str(prog.yml.target)} status is finished, proceeding.")

        # first check if child objects are registered with API (non-actions)
        if prog.yml.type != "action":
            if prog.yml.active_children:
                self.base.print_message(
                    f"Cannot sync {str(prog.yml.target)}, children are still 'active'."
                )
                return False
            if prog.yml.finished_children:
                # self.base.print_message(
                #     f"Cannot sync {str(prog.yml.target)}, children are not 'synced'."
                # )
                # self.base.print_message(
                #     "Adding 'finished' children to sync queue with highest priority."
                # )
                for child in prog.yml.finished_children:
                    if child.target.name not in self.running_tasks:
                        await self.enqueue_yml(child.target, rank - 1)
                        self.base.print_message(str(child.target))
                # self.base.print_message(
                #     f"Re-adding {str(prog.yml.target)} to sync queue with high priority."
                # )
                self.running_tasks.pop(prog.yml.target.name)
                await self.enqueue_yml(prog.yml.target, rank)
                self.base.print_message(f"{str(prog.yml.target)} re-queued, exiting.")
                return False

        # self.base.print_message(f"{str(prog.yml.target)} children are synced, proceeding.")

        # next push files to S3 (actions only)
        if prog.yml.type == "action":
            # re-check file lists
            # self.base.print_message(f"Checking file lists for {prog.yml.target.name}")
            prog.dict["files_pending"] += [
                str(p)
                for p in prog.yml.hlo_files + prog.yml.misc_files
                if p not in prog.dict["files_pending"]
                and p not in prog.dict["files_s3"]
            ]
            # push files to S3
            while prog.dict.get("files_pending", []):
                for sp in prog.dict["files_pending"]:
                    fp = Path(sp)
                    compress = False
                    self.base.print_message(
                        f"Pushing {sp} to S3 for {prog.yml.target.name}"
                    )
                    if fp.suffix == ".hlo":
                        compress = True
                        file_s3_key = (
                            f"raw_data/{meta['action_uuid']}/{fp.name}.json.gz"
                        )
                        self.base.print_message("Parsing hlo dicts.")
                        try:
                            file_meta, file_data = read_hlo(sp)
                        except Exception as err:
                            str_err = "".join(
                                traceback.format_exception(
                                    type(err), err, err.__traceback__
                                )
                            )
                            self.base.print_message(str_err)
                            file_meta = {}
                            file_data = {}
                        msg = {"meta": file_meta, "data": file_data}
                    else:
                        file_s3_key = f"raw_data/{meta['action_uuid']}/{fp.name}"
                        msg = fp
                    self.base.print_message(f"Destination: {file_s3_key}")
                    file_success = await self.to_s3(
                        msg=msg,
                        target=file_s3_key,
                        compress=compress,
                    )
                    if file_success:
                        self.base.print_message("Removing file from pending list.")
                        prog.dict["files_pending"].remove(sp)
                        self.base.print_message(
                            f"Adding file to S3 dict. {fp.name}: {file_s3_key}"
                        )
                        prog.dict["files_s3"].update({fp.name: file_s3_key})
                        self.base.print_message(f"Updating progress: {prog.dict}")

                        prog.write_dict()

        # if prog.yml is an experiment first check processes before pushing to API
        if prog.yml.type == "experiment":
            self.base.print_message(f"Finishing processes for {prog.yml.target.name}")
            retry_count = 0
            s3_unf, api_unf = prog.list_unfinished_procs()
            while s3_unf or api_unf:
                if retry_count == retries:
                    break
                await self.sync_process(prog, force=True)
                s3_unf, api_unf = prog.list_unfinished_procs()
                retry_count += 1
            if s3_unf or api_unf:
                self.base.print_message(
                    f"Processes in {str(prog.yml.target)} did not sync after 3 tries."
                )
                return False
            if prog.dict["process_metas"]:
                meta["process_list"] = [
                    d["process_uuid"]
                    for _, d in sorted(prog.dict["process_metas"].items())
                ]

        self.base.print_message(f"Patching model for {prog.yml.target.name}")
        patched_meta = {MOD_PATCH.get(k, k): v for k, v in meta.items()}
        prog.yml_model = MOD_MAP[prog.yml.type](**patched_meta).clean_dict(
            strip_private=True
        )

        # patch technique lists in prog.yml_model
        tech_name = prog.yml_model.get("technique_name", "NA")
        if isinstance(tech_name, list):
            split_technique = tech_name[prog.yml_model.get("action_split", 0)]
            prog.yml_model["technique_name"] = split_technique

        # next push prog.yml to S3
        if not prog.s3_done or force_s3:
            self.base.print_message(
                f"Pushing prog.yml->json to S3 for {prog.yml.target.name}"
            )
            uuid_key = patched_meta[f"{prog.yml.type}_uuid"]
            meta_s3_key = f"{prog.yml.type}/{uuid_key}.json"
            s3_success = await self.to_s3(prog.yml_model, meta_s3_key)
            if s3_success:
                prog.dict["s3"] = True
                prog.write_dict()

        # next push prog.yml to API
        if not prog.api_done or force_api:
            self.base.print_message(
                f"Pushing prog.yml to API for {prog.yml.target.name}"
            )
            api_success = await self.to_api(prog.yml_model, prog.yml.type)
            LOGGER.info(f"API push returned {api_success} for {prog.yml.target.name}")
            if api_success:
                prog.dict["api"] = True
                prog.write_dict()

        # get yml target name for popping later (after seq zip removes yml)
        yml_target_name = prog.yml.target.name
        yml_type = prog.yml.type

        # move to synced
        if prog.s3_done and prog.api_done:

            self.base.print_message(
                f"Moving files to RUNS_SYNCED for {yml_target_name}"
            )
            for lock_path in prog.yml.lock_files:
                lock_path.unlink()
            for file_path in prog.yml.misc_files + prog.yml.hlo_files:
                self.base.print_message(f"Moving {str(file_path)}")
                move_success = move_to_synced(file_path)
                while not move_success:
                    self.base.print_message(f"{file_path} is in use, retrying.")
                    sleep(1)
                    move_success = move_to_synced(file_path)

            # finally move yaml and update target
            LOGGER.info(f"Moving {yml_target_name} to RUNS_SYNCED")
            # with prog.yml.filelock:
            yml_success = move_to_synced(yml_path)
            if yml_success:
                result = prog.yml.cleanup()
                self.base.print_message(f"Cleanup {yml_target_name} {result}.")
                if result == "success":
                    self.base.print_message("yml_success")
                    prog = self.get_progress(Path(yml_success))
                    self.base.print_message("reassigning prog")
                    prog.dict["yml"] = str(yml_success)
                    self.base.print_message("updating progress")
                    prog.write_dict()

            # pop children from progress dict
            if yml_type in ["experiment", "sequence"]:
                children = prog.yml.children
                self.base.print_message(f"Removing children from progress: {children}.")
                for childyml in children:
                    # self.base.print_message(f"Clearing {childprog.yml.target.name}")
                    finished_child_path = childyml.finished_path.parent
                    if finished_child_path.exists():
                        self.try_remove_empty(str(finished_child_path))
                    # try:
                    #     self.progress.pop(childprog.yml.target.name)
                    # except Exception as err:
                    #     self.base.print_message(
                    #         f"Could not remove {childprog.yml.target.name}: {err}"
                    #     )
                self.try_remove_empty(str(prog.yml.finished_path.parent))

            if yml_type == "sequence":
                self.base.print_message(f"Zipping {prog.yml.target.parent.name}.")
                zip_target = prog.yml.target.parent.parent.joinpath(
                    f"{prog.yml.target.parent.name}.zip"
                )
                LOGGER.info(
                    f"Full sequence has synced, creating zip: {str(zip_target)}"
                )
                zip_dir(prog.yml.target.parent, zip_target)
                self.cleanup_root()
                # self.base.print_message(f"Removing sequence from progress.")
                # self.progress.pop(prog.yml.target.name)

            self.base.print_message(f"Removing {yml_target_name} from running_tasks.")
            self.running_tasks.pop(yml_target_name)

            # if action contributes processes, update processes
            if yml_type == "action" and meta.get("process_contrib", False):
                exp_prog = self.update_process(prog.yml, meta)
                await self.sync_process(exp_prog)

        return_dict = {k: d for k, d in prog.dict.items() if k != "process_metas"}
        return return_dict

    def update_process(self, act_yml: HelaoYml, act_meta: Dict):
        """Takes action yml and updates processes in exp parent."""
        exp_path = Path(act_yml.parent_path)
        exp_prog = self.get_progress(exp_path)
        # with exp_prog.prglock:
        act_idx = act_meta["action_order"]
        # handle legacy experiments (no process list)
        if exp_prog.dict["legacy_experiment"]:
            # if action is a process finisher, add to exp progress
            if act_meta["process_finish"]:
                exp_prog.dict["legacy_finisher_idxs"] = sorted(
                    set(exp_prog.dict["legacy_finisher_idxs"]).union([act_idx])
                )
            pf_idxs = exp_prog.dict["legacy_finisher_idxs"]
            pidx = (
                len(pf_idxs)
                if act_idx > max(pf_idxs + [-1])
                else pf_idxs.index(min(x for x in pf_idxs if x >= act_idx))
            )
            exp_prog.dict["process_groups"][pidx] = exp_prog.dict["process_groups"].get(
                pidx, []
            )
            exp_prog.dict["process_groups"][pidx].append(act_idx)
        else:
            pidx = [
                k for k, l in exp_prog.dict["process_groups"].items() if act_idx in l
            ][0]

            # if exp_prog doesn't yet have metadict, create one
            if pidx not in exp_prog.dict["process_metas"]:
                process_meta = {
                    k: v
                    for k, v in exp_prog.yml.meta.items()
                    if k
                    in [
                        "sequence_uuid",
                        "experiment_uuid",
                        "orchestrator",
                        "access",
                        "dummy",
                        "simulation",
                        "run_type",
                    ]
                }
                if "data_request_id" in exp_prog.yml.meta:
                    process_meta["data_request_id"] = exp_prog.yml.meta[
                        "data_request_id"
                    ]
                process_meta["process_params"] = exp_prog.yml.meta.get(
                    "experiment_params", {}
                )
                process_meta["technique_name"] = exp_prog.yml.meta.get(
                    "technique_name", exp_prog.yml.meta["experiment_name"]
                )
                process_list = exp_prog.yml.meta.get("process_list", [])
                process_input_str = f"{exp_prog.yml.meta['experiment_uuid']}__{pidx}"
                process_uuid = (
                    process_list[pidx]
                    if process_list
                    else str(gen_uuid(process_input_str))
                )
                process_meta["process_uuid"] = process_uuid
                process_meta["process_group_index"] = pidx
                process_meta["action_list"] = []

            else:
                process_meta = exp_prog.dict["process_metas"][pidx]

            # update experiment progress with action
            process_meta["action_list"].append(
                ShortActionModel(**act_meta).clean_dict(strip_private=True)
            )

            # self.base.print_message(f"current experiment progress:\n{exp_prog.dict}")
            if act_idx == min(exp_prog.dict["process_groups"][pidx]):
                process_meta["process_timestamp"] = act_meta["action_timestamp"]
            if "technique_name" in act_meta:
                process_meta["technique_name"] = act_meta["technique_name"]
            tech_name = process_meta["technique_name"]
            if isinstance(tech_name, list):
                split_technique = tech_name[act_meta.get("action_split", 0)]
                process_meta["technique_name"] = split_technique
            for pc in act_meta["process_contrib"]:
                if pc not in act_meta:
                    continue
                contrib = act_meta[pc]
                new_name = pc.replace("action_", "process_")
                if new_name not in process_meta:
                    process_meta[new_name] = contrib
                elif isinstance(contrib, dict):
                    process_meta[new_name].update(contrib)
                elif isinstance(contrib, list):
                    process_meta[new_name] += contrib
                else:
                    process_meta[new_name] = contrib
                # deduplicate sample lists
                if new_name in ["samples_in", "samples_out"]:
                    actuuid_order = {
                        x["action_uuid"]: x["orch_submit_order"]
                        for x in process_meta["action_list"]
                    }
                    sample_list = process_meta[new_name]
                    dedupe_dict = defaultdict(list)
                    deduped_samples = []
                    for si, x in enumerate(sample_list):
                        sample_label = x.get("global_label", False)
                        if not sample_label:
                            continue
                        actuuid = [
                            y for y in x["action_uuid"] if y in actuuid_order.keys()
                        ]
                        if not actuuid:
                            # self.base.print_message(
                            #     "no action_uuid for {sample_label}, using listed order"
                            # )
                            actorder = si
                        else:
                            actorder = actuuid_order[actuuid[0]]
                        dedupe_dict[sample_label].append((actorder, si))
                    if new_name == "samples_in":
                        deduped_samples = [
                            sample_list[min(v)[1]] for v in dedupe_dict.values()
                        ]
                    elif new_name == "samples_out":
                        deduped_samples = [
                            sample_list[max(v)[1]] for v in dedupe_dict.values()
                        ]
                    if deduped_samples:
                        process_meta[new_name] = deduped_samples
            # register finished action in process_actions_done {order: ymltargetname}
            exp_prog = self.get_progress(exp_path)
            exp_prog.dict["process_metas"][pidx] = process_meta
            exp_prog.dict["process_actions_done"].update({act_idx: act_yml.target.name})
            exp_prog.write_dict()
        return exp_prog

    async def sync_process(self, exp_prog: Progress, force: bool = False):
        """Pushes unfinished procesess to S3 & API from experiment progress."""
        s3_unfinished, api_unfinished = exp_prog.list_unfinished_procs()
        for pidx in s3_unfinished:
            pidx = pidx
            gids = exp_prog.dict["process_groups"][pidx]
            push_condition = False
            if force:
                push_condition = force
            elif exp_prog.dict["legacy_experiment"]:
                push_condition = max(gids) in exp_prog.dict[
                    "legacy_finisher_idxs"
                ] and all(i in exp_prog.dict["process_actions_done"] for i in gids)
            else:
                push_condition = (
                    all(i in exp_prog.dict["process_actions_done"] for i in gids)
                    and exp_prog.dict["process_metas"].get(pidx, {}) != {}
                )

            if push_condition:
                if pidx not in exp_prog.dict["process_metas"]:
                    push_condition = False
                    sync_path = os.path.dirname(str(exp_prog.prg))
                    self.reset_sync(sync_path)
                    await self.enqueue_yml(str(exp_prog.yml.target))
                    return exp_prog
                meta = exp_prog.dict["process_metas"][pidx]
                uuid_key = meta["process_uuid"]
                model = ProcessModel(**meta).clean_dict(strip_private=True)
                # write to local yml
                save_dir = os.path.dirname(
                    os.path.join(
                        self.base.helaodirs.process_root,
                        exp_prog.yml.relative_path,
                    )
                )
                save_yml_path = os.path.join(
                    save_dir, f"{pidx}__{uuid_key}__{meta['technique_name']}-prc.yml"
                )
                os.makedirs(save_dir, exist_ok=True)
                with open(save_yml_path, "w") as f:
                    f.write(yml_dumps(model))
                # sync to s3
                meta_s3_key = f"process/{uuid_key}.json"
                s3_success = await self.to_s3(model, meta_s3_key)
                if s3_success:
                    exp_prog.dict["process_s3"].append(pidx)
                    exp_prog.write_dict()
        for pidx in api_unfinished:
            gids = exp_prog.dict["process_groups"][pidx]
            if all(i in exp_prog.dict["process_actions_done"] for i in gids):
                meta = exp_prog.dict["process_metas"][pidx]
                model = ProcessModel(**meta).clean_dict(strip_private=True)
                api_success = await self.to_api(model, "process")
                if api_success:
                    exp_prog.dict["process_api"].append(pidx)
                    exp_prog.write_dict()
        return exp_prog

    async def to_s3(
        self,
        msg: Union[dict, Path],
        target: str,
        retries: int = 3,
        compress: bool = False,
    ):
        """Uploads to S3: dict sent as json, path sent as file."""
        try:
            if self.s3 is None:
                self.base.print_message("S3 is not configured. Skipping to S3 upload.")
                return True
            if isinstance(msg, dict):
                self.base.print_message("Converting dict to json.")
                uploaded = dict2json(msg)
                if compress:
                    if not target.endswith(".gz"):
                        target = f"{target}.gz"
                    uploaded = gzip.compress(uploaded.read())
                uploader = self.s3.upload_fileobj
            else:
                self.base.print_message("Converting path to str")
                uploaded = str(msg)
                uploader = self.s3.upload_file
            for i in range(retries + 1):
                if i > 0:
                    self.base.print_message(
                        f"S3 retry [{i}/{retries}]: {self.bucket}, {target}"
                    )
                try:
                    uploader(uploaded, self.bucket, target)
                    return True
                except Exception as err:
                    _ = "".join(
                        traceback.format_exception(type(err), err, err.__traceback__)
                    )
                    self.base.print_message(err)
                    await asyncio.sleep(5)
            self.base.print_message(f"Did not upload {target} after {retries} tries.")
            return False
        except Exception:
            LOGGER.error(f"Could not push {target}.", exc_info=True)

    async def to_api(self, req_model: dict, meta_type: str, retries: int = 3):
        """POST/PATCH model via Modelyst API."""
        if self.api_host is None:
            self.base.print_message(
                "Modelyst API is not configured. Skipping to API push."
            )
            return True
        req_url = f"https://{self.api_host}/{PLURALS[meta_type]}/"
        # self.base.print_message(f"preparing API push to {req_url}")
        # meta_name = req_model.get(
        #     f"{meta_type.replace('process', 'technique')}_name",
        #     req_model["experiment_name"],
        # )
        meta_uuid = req_model[f"{meta_type}_uuid"]
        self.base.print_message(f"attempting API push for {meta_type}: {meta_uuid}")
        try_create = True
        api_success = False
        last_status = 0
        last_response = {}
        self.base.print_message("creating async request session")
        async with aiohttp.ClientSession() as session:
            for i in range(retries):
                if not api_success:
                    self.base.print_message(f"session attempt {i}")
                    req_method = session.post if try_create else session.patch
                    api_str = f"API {'POST' if try_create else 'PATCH'}"
                    try:
                        self.base.print_message("trying request")
                        async with req_method(req_url, json=req_model) as resp:
                            self.base.print_message("response received")
                            if resp.status == 200:
                                api_success = True
                            elif resp.status == 400:
                                try_create = False
                            self.base.print_message(
                                f"[{i+1}/{retries}] {api_str} {meta_uuid} returned status: {resp.status}"
                            )
                            last_response = await resp.json()
                            self.base.print_message(
                                f"[{i+1}/{retries}] {api_str} {meta_uuid} response: {last_response}"
                            )
                            last_status = resp.status
                    except Exception as e:
                        self.base.print_message(
                            f"[{i+1}/{retries}] an exception occurred: {e}"
                        )
                        await asyncio.sleep(5)
                else:
                    break
            if not api_success:
                meta_s3_key = f"{meta_type}/{meta_uuid}.json"
                fail_model = {
                    "endpoint": f"https://{self.api_host}/{PLURALS[meta_type]}/",
                    "method": "POST" if try_create else "PATCH",
                    "status_code": last_status,
                    "detail": last_response.get("detail", ""),
                    "data": req_model,
                    "s3_files": [
                        {
                            "bucket_name": self.bucket,
                            "key": meta_s3_key,
                        }
                    ],
                }
                fail_url = f"https://{self.api_host}/failed"
                async with aiohttp.ClientSession() as session:
                    for _ in range(retries):
                        try:
                            async with session.post(fail_url, json=fail_model) as resp:
                                if resp.status == 200:
                                    self.base.print_message(
                                        f"successful debug API push for {meta_type}: {meta_uuid}"
                                    )
                                    break
                                self.base.print_message(
                                    f"failed debug API push for {meta_type}: {meta_uuid}"
                                )
                                self.base.print_message(
                                    f"response: {await resp.json()}"
                                )
                        except TimeoutError:
                            self.base.print_message(
                                f"unable to post failure model for {meta_type}: {meta_uuid}"
                            )
                            await asyncio.sleep(5)
        return api_success

    def list_pending(self, omit_manual_exps: bool = True):
        """Finds and queues ymls form RUNS_FINISHED."""
        finished_dir = str(self.base.helaodirs.save_root).replace(
            "RUNS_ACTIVE", "RUNS_FINISHED"
        )
        pending = glob(os.path.join(finished_dir, "**", "*-seq.yml"), recursive=True)
        if omit_manual_exps:
            pending = [x for x in pending if "manual_orch_seq" not in x]
        self.base.print_message(
            f"Found {len(pending)} pending sequences in RUNS_FINISHED."
        )
        return pending

    async def finish_pending(self, omit_manual_exps: bool = True):
        """Finds and queues sequence ymls from RUNS_FINISHED."""
        pending = self.list_pending(omit_manual_exps)
        self.base.print_message(
            f"Enqueueing {len(pending)} sequences from RUNS_FINISHED."
        )
        for pp in pending:
            if os.path.exists(
                pp.replace("RUNS_FINISHED", "RUNS_SYNCED").replace(".yml", ".progress")
            ):
                self.reset_sync(
                    os.path.dirname(pp).replace("RUNS_FINISHED", "RUNS_SYNCED")
                )
            await self.enqueue_yml(pp)
        return pending

    def reset_sync(self, sync_path: str):
        """Resets a synced sequence zip or partially-synced sequence folder."""
        if not os.path.exists(sync_path):
            self.base.print_message(f"{sync_path} does not exist.")
            return False
        if "RUNS_SYNCED" not in sync_path:
            self.base.print_message(
                f"Cannot reset path that's not in RUNS_SYNCED: {sync_path}"
            )
            return False
        ## if path is a zip
        if sync_path.endswith(".zip"):
            zf = ZipFile(sync_path)
            if any(x.endswith("-seq.prg") for x in zf.namelist()):
                seqzip_dir = os.path.dirname(sync_path)
                dest = os.path.join(
                    seqzip_dir.replace("RUNS_SYNCED", "RUNS_FINISHED"),
                    os.path.basename(sync_path).replace(".zip", ""),
                )
                os.makedirs(dest, exist_ok=True)
                no_lock_prg = [
                    x
                    for x in zf.namelist()
                    if not x.endswith(".prg") and not x.endswith(".lock")
                ]
                zf.extractall(dest, members=no_lock_prg)
                zf.close()
                if not os.path.exists(sync_path.replace(".zip", ".orig")):
                    shutil.move(sync_path, sync_path.replace(".zip", ".orig"))
                self.base.print_message(f"Restored zip to {dest}")
                return True
            zf.close()
            self.base.print_message("Zip does not contain a valid sequence.")
            return False

        ## if path is a directory
        elif os.path.isdir(sync_path):
            base_prgs = [
                x
                for x in glob(os.path.join(sync_path, "**", "*-*.pr*"), recursive=True)
                if x.endswith(".progress") or x.endswith(".prg") or x.endswith(".lock")
            ]
            # seq_prgs = [x for x in base_prgs if "-seq.pr" in x]
            # for x in seq_prgs:
            #     base_prgs = [
            #         y for y in base_prgs if not y.startswith(os.path.dirname(x))
            #     ]
            # exp_prgs = [x for x in base_prgs if "-exp.pr" in x]
            # for x in exp_prgs:
            #     base_prgs = [
            #         y for y in base_prgs if not y.startswith(os.path.dirname(x))
            #     ]
            # act_prgs = [x for x in base_prgs if "-act.pr" in x]
            # for x in act_prgs:
            #     base_prgs = [
            #         y for y in base_prgs if not y.startswith(os.path.dirname(x))
            #     ]

            # base_prgs = act_prgs + exp_prgs + seq_prgs

            if not base_prgs:
                self.base.print_message(
                    f"Did not find any .prg or .progress files in subdirectories of {sync_path}"
                )
                self.unsync_dir(sync_path)

            else:
                self.base.print_message(
                    f"Found {len(base_prgs)} .prg, .progress, or .lock files in subdirectories of {sync_path}"
                )
                # remove all .prg files and lock files
                for prg in base_prgs:
                    base_dir = os.path.dirname(prg)
                    sub_prgs = [
                        x
                        for x in glob(
                            os.path.join(base_dir, "**", "*-*.pr*"), recursive=True
                        )
                        if x.endswith(".progress") or x.endswith(".prg")
                    ]
                    sub_lock = [
                        x
                        for x in glob(
                            os.path.join(base_dir, "**", "*.lock"), recursive=True
                        )
                    ]
                    self.base.print_message(
                        f"Removing {len(base_prgs) + len(sub_lock)} prg and progress files in subdirectories of {base_dir}"
                    )
                    for sp in sub_prgs + sub_lock:
                        os.remove(sp)

                    # move path back to RUNS_FINISHED
                    self.unsync_dir(base_dir)

            seq_zips = glob(os.path.join(sync_path, "**", "*.zip"), recursive=True)
            if not seq_zips:
                self.base.print_message(
                    f"Did not find any zip files in subdirectories of {sync_path}"
                )
            else:
                self.base.print_message(
                    f"Found {len(seq_zips)} zip files in subdirectories of {sync_path}"
                )
                for seq_zip in seq_zips:
                    self.reset_sync(seq_zip)
            return True
        self.base.print_message("Arg was not a sequence path or zip.")
        return False

    def shutdown(self):
        pass

    def unsync_dir(self, sync_dir: str):
        for fp in glob(os.path.join(sync_dir, "**", "*"), recursive=True):
            if fp.endswith(".lock") or fp.endswith(".progress") or fp.endswith(".prg"):
                os.remove(fp)
            elif not os.path.isdir(fp):
                tp = os.path.dirname(fp.replace("RUNS_SYNCED", "RUNS_FINISHED"))
                os.makedirs(tp, exist_ok=True)
                shutil.move(fp, tp)
        self.base.print_message(f"Successfully reverted {sync_dir}")
