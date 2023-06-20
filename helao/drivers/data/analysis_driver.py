"""Data analysis driver

Handles Helao analyses uploads to S3.

"""

__all__ = ["HelaoAnalysisSyncer"]

import asyncio
import os
import traceback
from copy import copy
from datetime import datetime
from pathlib import Path
from typing import Union, Optional, Tuple
from uuid import UUID

import aiohttp
import boto3
import botocore.exceptions
import pandas as pd

from helao.helpers.print_message import print_message
from helao.servers.base import Base
from helao.drivers.data.sync_driver import dict2json
from helao.drivers.data.analyses.echeuvis_stability import (
    EcheUvisLoader,
    EcheUvisAnalysis,
    ANALYSIS_DEFAULTS as ECHEUVIS_DEFAULTS,
)


MAX_TASKS = 4


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

        self.syncer_loop = asyncio.create_task(self.syncer(), name="syncer_loop")

    def sync_exit_callback(self, task: asyncio.Task):
        task_name = task.get_name()
        if task_name in self.running_tasks:
            self.running_tasks.pop(task_name)
            try:
                self.task_set.remove(task_name)
            except KeyError:
                pass

    async def enqueue_calc(
        self, calc_tup: Tuple[UUID, pd.DataFrame, dict], rank: int = 5
    ):
        """Adds (process_uuid, query_df, ana_params) tuple to calculation queue."""
        self.task_set.add(calc_tup[0])
        await self.task_queue.put((rank, calc_tup))
        self.base.print_message(
            f"Added {str(calc_tup[0])} to syncer queue with priority {rank}."
        )

    async def syncer(self):
        """Syncer loop coroutine which consumes the task queue."""
        while True:
            if len(self.running_tasks) < MAX_TASKS:
                rank, ana = await self.task_queue.get()
                if ana.analysis_uuid not in self.running_tasks:
                    self.running_tasks[ana.analysis_uuid] = asyncio.create_task(
                        self.sync_ana(ana, rank), name=ana.analysis_uuid
                    )
                    self.running_tasks[ana.analysis_uuid].add_done_callback(
                        self.sync_exit_callback
                    )
            await asyncio.sleep(0.1)

    async def sync_ana(
        self, calc_tup: Tuple[UUID, pd.DataFrame, dict], retries: int = 3, rank: int = 5
    ):
        eua = EcheUvisAnalysis(*calc_tup)
        eua.calc_output()
        model_dict, output_dict = eua.export_analysis()
        s3_model_target = f"analysis/{eua.analysis_uuid}.json"
        s3_output_target = f"analysis/{eua.analysis_uuid}_output.json"

        s3_model_success = await self.to_s3(model_dict, s3_model_target)
        s3_output_success = await self.to_s3(output_dict, s3_output_target)
        api_success = await self.to_api(model_dict)

        if s3_model_success and s3_output_success and api_success:
            self.base.print_message(f"Successfully synced {eua.analysis_uuid}")
            return True

        self.base.print_message(f"Analysis {eua.analysis_uuid} sync failed.")
        return False

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

    async def to_api(self, req_model: dict, retries: int = 3):
        """POST/PATCH model via Modelyst API."""
        req_url = f"https://{self.api_host}/analyses/"
        meta_uuid = req_model["analysis_uuid"]
        self.base.print_message(f"attempting API push for analysis: {meta_uuid}")
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
                meta_s3_key = f"analysis/{meta_uuid}.json"
                fail_model = {
                    "endpoint": f"https://{self.api_host}/analysis/",
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
                                    f"successful debug API push for analysis: {meta_uuid}"
                                )
                                break
                            self.base.print_message(
                                f"failed debug API push for analysis: {meta_uuid}"
                            )
                            self.base.print_message(f"response: {await resp.json()}")
        return api_success

    async def batch_calc_echeuvis(
        self,
        plate_id: Optional[int] = None,
        sequence_uuid: Optional[UUID] = None,
        params: dict = {},
    ):
        """Generate list of EcheUvisAnalysis from sequence or plate_id (latest seq)."""
        eul = EcheUvisLoader(
            awscli_profile_name=self.config_dict["aws_profile"], cache_s3=True
        )
        df = eul.get_recent(
            min_date=datetime.now().strftime("%Y-%m-%d"), plate_id=plate_id
        )

        # all processes in sequence
        pdf = df.sort_values(
            ["sequence_timestamp", "process_timestamp"], ascending=False
        )
        if sequence_uuid is not None:
            pdf = pdf.query("sequence_uuid==@sequence_uuid")
        pdf = pdf.query("sequence_timestamp==sequence_timestamp.max()")

        # only SPEC actions during CA
        eudf = (
            pdf.query("experiment_name=='ECHEUVIS_sub_CA_led'")
            .query("run_use=='data'")
            .query("action_name=='acquire_spec_extrig'")
        )
        ana_params = copy(ECHEUVIS_DEFAULTS)
        for puuid in eudf.process_uuid:
            await self.enqueue_calc((puuid, pdf, ana_params.update(params)))

    def shutdown(self):
        pass


# for each EcheUvisAnalysis:
# populate HelaoAnalysis model
# write ana.outputs.json() to s3 bucket
# push HelaoAnalysis to API
