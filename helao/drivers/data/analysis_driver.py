"""Data analysis driver

Handles Helao analyses uploads to S3.

"""

__all__ = ["HelaoAnalysisSyncer"]

import asyncio
import os
import shutil
import traceback
from datetime import datetime
from glob import glob
from pathlib import Path
from typing import Union
from zipfile import ZipFile

import aiohttp
import boto3
import botocore.exceptions
import numpy as numpy

from helao.helpers.print_message import print_message
from helao.helpers.zip_dir import zip_dir
from helao.servers.base import Base
from helao.drivers.data.analyses.echeuvis_stability import batch_calc_echeuvis


# batch_calc_echeuvis returns list of EcheUvisAnalysis using plate_id and params
# for each EcheUvisAnalysis:
    # populate HelaoAnalysis model
    # write ana.outputs.json() to s3 bucket
    # push HelaoAnalysis to API

class HelaoAnalysisSyncer:
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
            # self.base.print_message(f"Removing {task_name} from running_tasks.")
            self.running_tasks.pop(task_name)
            try:
                self.task_set.remove(task_name)
            except KeyError:
                pass
        # else:
        #     self.base.print_message(
        #         f"{task_name} was already removed from running_tasks."
        #     )

    async def syncer(self):
        """Syncer loop coroutine which consumes the task queue."""
        while True:
            if len(self.running_tasks) < MAX_TASKS:
                # self.base.print_message("Getting next yml_target from queue.")
                rank, yml_target = await self.task_queue.get()
                # self.base.print_message(
                #     f"Acquired {yml_target.name} with priority {rank}."
                # )
                if yml_target.name not in self.running_tasks:
                    # self.base.print_message(
                    #     f"Creating sync task for {yml_target.name}."
                    # )
                    self.running_tasks[yml_target.name] = asyncio.create_task(
                        self.sync_yml(yml_target, rank), name=yml_target.name
                    )
                    self.running_tasks[yml_target.name].add_done_callback(
                        self.sync_exit_callback
                    )
                # else:
                #     print_message(f"{yml_target} sync is already in progress.")
            await asyncio.sleep(0.1)

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
        async with aiohttp.ClientSession() as session:
            for i in range(retries):
                if not api_success:
                    req_method = session.post if try_create else session.patch
                    api_str = f"API {'POST' if try_create else 'PATCH'}"
                    try:
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
                    except Exception as e:
                        self.base.print_message(
                            f"[{i+1}/{retries}] an exception occurred: {e}"
                        )
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
                zf.extractall(dest)
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
                if x.endswith(".progress") or x.endswith(".prg")
            ]
            seq_prgs = [x for x in base_prgs if "-seq.pr" in x]
            for x in seq_prgs:
                base_prgs = [
                    y for y in base_prgs if not y.startswith(os.path.dirname(x))
                ]
            exp_prgs = [x for x in base_prgs if "-exp.pr" in x]
            for x in exp_prgs:
                base_prgs = [
                    y for y in base_prgs if not y.startswith(os.path.dirname(x))
                ]
            act_prgs = [x for x in base_prgs if "-act.pr" in x]
            for x in act_prgs:
                base_prgs = [
                    y for y in base_prgs if not y.startswith(os.path.dirname(x))
                ]

            base_prgs = act_prgs + exp_prgs + seq_prgs

            if not base_prgs:
                self.base.print_message(
                    f"Did not find any .prg or .progress files in subdirectories of {sync_path}"
                )
            else:
                self.base.print_message(
                    f"Found {len(base_prgs)} .prg or .progress files in subdirectories of {sync_path}"
                )
                # remove all .prg files
                for prg in base_prgs:
                    base_dir = os.path.dirname(prg)
                    sub_prgs = [
                        x
                        for x in glob(
                            os.path.join(base_dir, "**", "*-*.pr*"), recursive=True
                        )
                        if x.endswith(".progress") or x.endswith(".prg")
                    ]
                    self.base.print_message(
                        f"Removing {len(base_prgs)} prg and progress files in subdirectories of {base_dir}"
                    )
                    for sp in sub_prgs:
                        os.remove(sp)
                    # move path back to RUNS_FINISHED
                    shutil.move(
                        base_dir, base_dir.replace("RUNS_SYNCED", "RUNS_FINISHED")
                    )
                    self.base.print_message(f"Successfully reverted {base_dir}")

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
