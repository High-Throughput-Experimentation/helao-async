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
import io
import codecs
import json
import asyncio
from ruamel.yaml import YAML
from pathlib import Path
from datetime import datetime
from typing import Union, Optional, Dict, List
import traceback

import pyaml
import botocore.exceptions
import boto3
from helao.servers.base import Base
from helaocore.models.process import ProcessModel
from helaocore.models.action import ShortActionModel, ActionModel
from helaocore.models.experiment import ExperimentModel
from helaocore.models.sequence import SequenceModel
from helao.helpers.gen_uuid import gen_uuid
from helao.helpers.read_hlo import read_hlo
from helao.helpers.print_message import print_message
from helao.helpers.zip_dir import zip_dir


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
YAML_LOADER = YAML(typ="safe")
MAX_TASKS = 4


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
        file_path.replace(target_path)
        return target_path
    except PermissionError:
        return False


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
        if not self.target.exists():
            return "success"
        tempparts = list(self.parts)
        steps = len(tempparts) - self.status_idx
        for i in range(1, steps):
            check_dir = Path(os.path.join(*tempparts[:-i]))
            contents = [x for x in check_dir.glob("*") if x != check_dir]
            if contents:
                print(f"{str(check_dir)} is not empty")
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
        self.target.write_text(
            str(pyaml.dump(meta_dict, safe=True, sort_dicts=False)), encoding="utf-8"
        )


class Progress:
    yml: HelaoYml
    prg: Path
    dict: Dict

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
                    "process_finisher_idxs": [],  # end action indices (submit order)
                    "process_finished_idxs": [],  # finished action indices
                    "process_groups": {},  # {process_idx: contributor action indices}
                    "process_metas": {},  # {process_idx: yml_dict}
                    "process_s3": [],  # list of process_idx with S3 done
                    "process_api": [],  # list of process_idx with API done
                }
                self.dict.update(exp_dict)
            self.write_dict()
        else:
            self.read_dict()

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
        self.dict = YAML_LOADER.load(self.prg)

    def write_dict(self, new_dict: Optional[Dict] = None):
        out_dict = self.dict if new_dict is None else new_dict
        self.prg.write_text(
            str(pyaml.dump(out_dict, safe=True, sort_dicts=False)), encoding="utf-8"
        )

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
        self.sequence_objs = {}
        self.task_queue = asyncio.PriorityQueue()
        self.task_set = set()
        self.running_tasks = {}
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
            self.base.print_message(f"Removing {task_name} from running_tasks.")
            self.running_tasks.pop(task_name)
            self.task_set.remove(task_name)
        else:
            self.base.print_message(
                f"{task_name} was already removed from running_tasks."
            )

    async def syncer(self):
        """Syncer loop coroutine which consumes the task queue."""
        while True:
            if len(self.running_tasks) < MAX_TASKS:
                self.base.print_message("Getting next yml_target from queue.")
                priority, yml_target = await self.task_queue.get()
                self.base.print_message(
                    f"Acquired {yml_target.name} with priority {priority}."
                )
                if yml_target.name not in self.running_tasks:
                    self.base.print_message(
                        f"Creating sync task for {yml_target.name}."
                    )
                    self.running_tasks[yml_target.name] = asyncio.create_task(
                        self.sync_yml(yml_target), name=yml_target.name
                    )
                    self.running_tasks[yml_target.name].add_done_callback(
                        self.sync_exit_callback
                    )
                else:
                    print_message(f"{yml_target} sync is already in progress.")
            await asyncio.sleep(0.1)

    def get_progress(self, yml_path: Path):
        """Returns progress from global dict, updates yml_path if yml path not found."""
        if yml_path.name in self.progress:
            prog = self.progress[yml_path.name]
            if not prog.yml.exists:
                prog.yml.check_paths()
                prog.dict.update({"yml": str(prog.yml.target)})
                prog.write_dict()
        else:
            if not yml_path.exists():
                hy = HelaoYml(yml_path)
                hy.check_paths()
                prog = Progress(hy.target)
                prog.write_dict()
            else:
                prog = Progress(yml_path)
        self.progress[yml_path.name] = prog
        return self.progress[yml_path.name]

    async def enqueue_yml(self, upath: Union[Path, str], rank: int = 2):
        """Adds yml to sync queue, defaulting to lowest priority."""
        yml_path = Path(upath) if isinstance(upath, str) else upath
        self.task_set.add(yml_path.name)
        await self.task_queue.put((rank, yml_path))
        self.base.print_message(
            f"Added {str(yml_path)} to syncer queue with priority {rank}."
        )

    async def sync_yml(self, yml_path: Path, retries: int = 3):
        """Coroutine for syncing a single yml"""
        prog = self.get_progress(yml_path)
        if not prog:
            self.base.print_message(
                f"{str(yml_path)} does not exist, assume yml has moved to synced."
            )
            return True
        yml = prog.yml
        meta = yml.meta

        if yml.status == "synced":
            self.base.print_message(
                f"Cannot sync {str(yml.target)}, status is already 'synced'."
            )
            return True

        self.base.print_message(
            f"{str(yml.target)} status is not synced, checking for finished."
        )

        if yml.status == "active":
            self.base.print_message(
                f"Cannot sync {str(yml.target)}, status is not 'finished'."
            )
            return False

        self.base.print_message(f"{str(yml.target)} status is finished, proceeding.")

        # first check if child objects are registered with API (non-actions)
        if yml.type != "action":
            if yml.active_children:
                self.base.print_message(
                    f"Cannot sync {str(yml.target)}, children are still 'active'."
                )
                return False
            if yml.finished_children:
                self.base.print_message(
                    f"Cannot sync {str(yml.target)}, children are not 'synced'."
                )
                self.base.print_message(
                    "Adding 'finished' children to sync queue with highest priority."
                )
                for child in yml.finished_children:
                    if (
                        child.target.name not in self.task_set
                        and child.target.name not in self.running_tasks
                    ):
                        await self.enqueue_yml(child.target, 0)
                        self.base.print_message(str(child.target))
                self.base.print_message(
                    f"Re-adding {str(yml.target)} to sync queue with high priority."
                )
                self.running_tasks.pop(yml.target.name)
                self.task_set.remove(yml.target.name)
                await self.enqueue_yml(yml.target, 1)
                self.base.print_message(f"{str(yml.target)} re-queued, exiting.")
                return False

        self.base.print_message(f"{str(yml.target)} children are synced, proceeding.")

        # next push files to S3 (actions only)
        if yml.type == "action":
            # re-check file lists
            self.base.print_message(f"Checking file lists for {yml.target.name}")
            prog.dict["files_pending"] += [
                p
                for p in yml.hlo_files + yml.misc_files
                if p not in prog.dict["files_pending"]
                and p not in prog.dict["files_s3"]
            ]
            # push files to S3
            while prog.dict.get("files_pending", []):
                for fp in prog.dict["files_pending"]:
                    self.base.print_message(
                        f"Pushing {str(fp)} to S3 for {yml.target.name}"
                    )
                    if fp.suffix == ".hlo":
                        file_s3_key = f"raw_data/{meta['action_uuid']}/{fp.name}.json"
                        file_meta, file_data = read_hlo(str(fp))
                        msg = {"meta": file_meta, "data": file_data}
                    else:
                        file_s3_key = f"raw_data/{meta['action_uuid']}/{fp.name}"
                        msg = fp
                    file_success = await self.to_s3(msg, file_s3_key)
                    if file_success:
                        prog.dict["files_pending"].remove(fp)
                        prog.dict["files_s3"].update({fp.name: file_s3_key})
                        prog.write_dict()

        # if yml is an experiment first check processes before pushing to API
        if yml.type == "experiment":
            self.base.print_message(f"Finishing processes for {yml.target.name}")
            retry_count = 0
            s3_unf, api_unf = prog.list_unfinished_procs()
            while s3_unf or api_unf:
                if retry_count == retries:
                    break
                await self.sync_process(prog)
                s3_unf, api_unf = prog.list_unfinished_procs()
                retry_count += 1
            if s3_unf or api_unf:
                self.base.print_message(
                    f"Processes in {str(yml.target)} did not sync after 3 tries."
                )
                return False
            if prog.dict["process_metas"]:
                meta["process_list"] = [
                    d["process_uuid"]
                    for _, d in sorted(prog.dict["process_metas"].items())
                ]

        self.base.print_message(f"Patching model for {yml.target.name}")
        patched_meta = {MOD_PATCH.get(k, k): v for k, v in meta.items()}
        yml_model = MOD_MAP[yml.type](**patched_meta).clean_dict()

        # next push yml to S3
        if not prog.s3_done:
            self.base.print_message(f"Pushing yml->json to S3 for {yml.target.name}")
            uuid_key = patched_meta[f"{yml.type}_uuid"]
            meta_s3_key = f"{yml.type}/{uuid_key}.json"
            s3_success = await self.to_s3(yml_model, meta_s3_key)
            if s3_success:
                prog.dict["s3"] = True
                prog.write_dict()

        # next push yml to API
        if not prog.api_done:
            self.base.print_message(f"Pushing yml to API for {yml.target.name}")
            api_success = await self.to_api(yml_model, yml.type)
            self.base.print_message(
                f"API push returned {api_success} for {yml.target.name}"
            )
            if api_success:
                prog.dict["api"] = True
                prog.write_dict()

        # move to synced
        if prog.s3_done and prog.api_done:
            self.base.print_message(
                f"Moving files to RUNS_SYNCED for {yml.target.name}"
            )
            for file_path in yml.misc_files + yml.hlo_files:
                self.base.print_message(f"Moving {str(file_path)}")
                move_success = move_to_synced(file_path)
                while not move_success:
                    self.base.print_message(f"{file_path} is in use, retrying.")
                    sleep(1)
                    move_success = move_to_synced(file_path)

            # finally move yaml and update target
            self.base.print_message(f"Moving {yml.target.name} to RUNS_SYNCED")
            yml_success = move_to_synced(yml_path)
            if yml_success:
                result = yml.cleanup()
                self.try_remove_empty(yml.target.parent)
                self.base.print_message(f"Cleanup {yml.target.name} {result}.")
                if result == "success":
                    prog.yml = HelaoYml(yml_success)
                    yml = prog.yml
                    prog.dict["yml"] = str(yml_success)
                    prog.write_dict()

            # pop children from progress dict
            if yml.type in ["experiment", "sequence"]:
                children = yml.children
                self.base.print_message(f"Removing children from progress: {children}.")
                for childyml in children:
                    self.base.print_message(f"Clearing {childyml.target.name}")
                    try:
                        self.progress.pop(childyml.target.name)
                    except Exception as err:
                        self.base.print_message(
                            f"Could not remove {childyml.target.name}: {err}"
                        )

            if yml.type == "sequence":
                self.base.print_message(f"Zipping {yml.target.parent.name}.")
                zip_target = yml.target.parent.parent.joinpath(
                    f"{yml.target.parent.name}.zip"
                )
                self.base.print_message(
                    f"Full sequence has synced, creating zip: {str(zip_target)}"
                )
                zip_dir(yml.target.parent, zip_target)
                self.cleanup_root()
                self.base.print_message(f"Removing sequence from progress.")
                self.progress.pop(yml.target.name)

            self.base.print_message(f"Removing task from running_tasks.")
            self.running_tasks.pop(yml.target.name)

        # if action contributes processes, update processes
        if yml.type == "action" and meta.get("process_contrib", False):
            exp_prog = self.update_process(yml, meta)
            if meta.get("process_finish", False):
                await self.sync_process(exp_prog)

        return_dict = {k: d for k, d in prog.dict.items() if k != "process_metas"}
        return return_dict

    def update_process(self, act_yml: HelaoYml, act_meta: Dict):
        """Takes action yml and updates processes in exp parent."""
        exp_path = Path(act_yml.parent_path)
        exp_prog = self.get_progress(exp_path)
        act_idx = act_meta["action_order"]
        # if action is a process finisher, add to exp progress
        if act_meta["process_finish"]:
            exp_prog.dict["process_finisher_idxs"] = sorted(
                set(exp_prog.dict["process_finished_idxs"]).union([act_idx])
            )
        exp_prog.dict["process_finished_idxs"] = sorted(
            set(exp_prog.dict["process_finished_idxs"]).union([act_idx])
        )
        pf_idxs = exp_prog.dict["process_finisher_idxs"]
        pidx = (
            len(pf_idxs)
            if act_idx > max(pf_idxs + [-1])
            else pf_idxs.index(min(x for x in pf_idxs if x >= act_idx))
        )
        exp_prog.dict["process_groups"][pidx] = exp_prog.dict["process_groups"].get(
            pidx, []
        )
        exp_prog.dict["process_groups"][pidx].append(act_idx)

        # if exp_prog doesn't yet have metadict, create one
        if pidx not in exp_prog.dict["process_metas"]:
            exp_prog.dict["process_metas"][pidx] = {
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
            exp_prog.dict["process_metas"][pidx][
                "technique_name"
            ] = exp_prog.yml.meta.get(
                "technique_name", exp_prog.yml.meta["experiment_name"]
            )
            exp_prog.dict["process_metas"][pidx]["process_uuid"] = str(gen_uuid())
            exp_prog.dict["process_metas"][pidx]["process_group_index"] = pidx
            exp_prog.dict["process_metas"][pidx]["action_list"] = []

        # update experiment progress with action
        exp_prog.dict["process_metas"][pidx]["action_list"].append(
            ShortActionModel(**act_meta).clean_dict()
        )

        self.base.print_message(f"current experiment progress:\n{exp_prog.dict}")
        if act_idx == min(exp_prog.dict["process_groups"][pidx]):
            exp_prog.dict["process_metas"][pidx]["process_timestamp"] = act_meta[
                "action_timestamp"
            ]
        for pc in act_meta["process_contrib"]:
            if pc not in act_meta:
                continue
            contrib = act_meta[pc]
            new_name = pc.replace("action_", "process_")
            if new_name not in exp_prog.dict["process_metas"][pidx]:
                exp_prog.dict["process_metas"][pidx][new_name] = contrib
            elif isinstance(contrib, dict):
                exp_prog.dict["process_metas"][pidx][new_name].update(contrib)
            elif isinstance(contrib, list):
                exp_prog.dict["process_metas"][pidx][new_name] += contrib
            else:
                exp_prog.dict["process_metas"][pidx][new_name] = contrib
        exp_prog.write_dict()
        return exp_prog

    async def sync_process(self, exp_prog: Progress):
        """Pushes unfinished procesess to S3 & API from experiment progress."""
        s3_unfinished, api_unfinished = exp_prog.list_unfinished_procs()
        for pidx in s3_unfinished:
            gids = exp_prog.dict["process_groups"][pidx]
            if all([i in exp_prog.dict["process_finished_idxs"] for i in gids]):
                meta = exp_prog.dict["process_metas"][pidx]
                # sync to s3
                uuid_key = meta["process_uuid"]
                meta_s3_key = f"process/{uuid_key}.json"
                s3_success = await self.to_s3(meta, meta_s3_key)
                if s3_success:
                    exp_prog.dict["process_s3"].append(pidx)
                    exp_prog.write_dict()
        for pidx in api_unfinished:
            gids = exp_prog.dict["process_groups"][pidx]
            if all([i in exp_prog.dict["process_finished_idxs"] for i in gids]):
                meta = exp_prog.dict["process_metas"][pidx]
                model = MOD_MAP["process"](**meta).clean_dict()
                api_success = await self.to_api(model, "process")
                if api_success:
                    exp_prog.dict["process_api"].append(pidx)
                    exp_prog.write_dict()
        return exp_prog

    async def to_s3(self, msg: Union[dict, Path], target: str, retries: int = 3):
        """Uploads to S3: dict sent as json, path sent as file."""
        if isinstance(msg, dict):
            uploaded = dict2json(msg)
            uploader = self.s3.upload_fileobj
        else:
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
            except botocore.exceptions.ClientError as err:
                _ = "".join(
                    traceback.format_exception(type(err), err, err.__traceback__)
                )
                self.base.print_message(err)
                await asyncio.sleep(1)
        self.base.print_message(f"Did not upload {target} after {retries} tries.")
        return False

    async def to_api(self, req_model: dict, meta_type: str, retries: int = 3):
        """POST/PATCH model via Modelyst API."""
        req_url = f"https://{self.api_host}/{PLURALS[meta_type]}/"
        self.base.print_message(f"preparing API push to {req_url}")
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
        async with aiohttp.ClientSession() as session:
            for i in range(retries):
                if not api_success:
                    req_method = session.post if try_create else session.patch
                    api_str = f"API {'POST' if try_create else 'PATCH'}"
                    async with req_method(req_url, json=req_model) as resp:
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
                        async with session.post(fail_url, json=fail_model) as resp:
                            if resp.status == 200:
                                self.base.print_message(
                                    f"successful debug API push for {meta_type}: {meta_uuid}"
                                )
                                break
                            self.base.print_message(
                                f"failed debug API push for {meta_type}: {meta_uuid}"
                            )
                            self.base.print_message(f"response: {await resp.json()}")
        return api_success
