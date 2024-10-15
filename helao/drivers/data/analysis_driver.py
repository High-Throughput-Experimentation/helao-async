"""Data analysis driver

Handles Helao analyses uploads to S3.

"""

__all__ = ["HelaoAnalysisSyncer"]

from helao.helpers import logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(logger_name="analysis_driver_standalone")
else:
    LOGGER = logging.LOGGER

import time
import asyncio
import traceback
import os
from datetime import datetime
from pathlib import Path
from typing import Union, Optional, Tuple
from uuid import UUID
import gzip

import aiohttp
import json
import botocore.exceptions
import pandas as pd

from helao.servers.base import Base
from helao.helpers.set_time import set_time
from helao.helpers.yml_tools import yml_dumps
from helao.drivers.data.sync_driver import dict2json, HelaoSyncer
from helao.drivers.data.loaders import pgs3
from helao.drivers.data.loaders.localfs import LocalLoader
from helao.drivers.data.analyses.echeuvis_stability import (
    EcheUvisAnalysis,
    SDCUVIS_QUERY,
)
from helao.drivers.data.analyses.uvis_bkgsubnorm import DryUvisAnalysis, DRYUVIS_QUERY
from helao.drivers.data.analyses.icpms_local import IcpmsAnalysis

from helao.helpers import logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(logger_name="sync_driver_standalone")
else:
    LOGGER = logging.LOGGER


class HelaoAnalysisSyncer(HelaoSyncer):
    base: Base
    running_tasks: dict

    def __init__(self, action_serv: Base):
        """Pushes yml to S3 and API."""
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.world_config = action_serv.world_cfg
        self.local_ana_root = os.path.join(self.world_config["root"], "ANALYSES")
        self.max_tasks = self.config_dict.get("max_tasks", 4)
        # declare global loader for analysis models used by driver.batch_* methods
        self.get_loader()
        # self.api_host = self.config_dict["api_host"]

        self.task_queue = asyncio.PriorityQueue()
        self.task_set = set()
        self.running_tasks = {}

        self.syncer_loop = asyncio.create_task(self.syncer(), name="syncer_loop")

    def get_loader(self):
        pgs3.LOADER = pgs3.EcheUvisLoader(
            self.config_dict["env_file"],
            cache_s3=False,
            cache_json=False,
            cache_sql=False,
        )
        self.s3 = pgs3.LOADER.cli
        self.s3r = pgs3.LOADER.res
        # os.environ["AWS_CONFIG_FILE"] = self.config_dict["aws_config_path"]
        # self.aws_session = boto3.Session(profile_name=self.config_dict["aws_profile"])
        # self.s3 = self.aws_session.client("s3")
        self.bucket = pgs3.LOADER.s3_bucket
        self.region = pgs3.LOADER.s3_region

    def sync_exit_callback(self, task: asyncio.Task):
        task_name = task.get_name()
        if task_name in self.running_tasks:
            self.running_tasks.pop(task_name)
            try:
                self.task_set.remove(task_name)
            except KeyError:
                pass

    async def enqueue_calc(
        self, calc_tup: Tuple[UUID, pd.DataFrame, dict, str], rank: int = 5
    ):
        """Adds (process_uuid, query_df, ana_params) tuple to calculation queue."""
        self.task_set.add(calc_tup[0])
        await self.task_queue.put((rank, calc_tup))
        self.base.print_message(
            f"Added {str(calc_tup[0])} to syncer queue with priority {rank}."
        )

    async def syncer(self):
        """Syncer loop coroutine which consumes the task queue."""
        self.base.print_message("Starting syncer queue processor task.")
        while True:
            if len(self.running_tasks) < self.max_tasks:
                rank, calc_tup = await self.task_queue.get()
                self.base.print_message(f"creating ana task for {calc_tup[0]}.")
                self.running_tasks[str(calc_tup[0])] = asyncio.create_task(
                    self.sync_ana(calc_tup, rank=rank), name=str(calc_tup[0])
                )
                self.running_tasks[str(calc_tup[0])].add_done_callback(
                    self.sync_exit_callback
                )
                self.task_queue.task_done()
            await asyncio.sleep(0.1)

    async def sync_ana(
        self,
        calc_tup: Tuple[UUID, pd.DataFrame, dict, str],
        retries: int = 3,
        rank: int = 5,
    ):
        process_uuid, process_df, analysis_params, ana_func = calc_tup
        # self.base.print_message(f"performing analysis {analysis_name}")
        # self.base.print_message(f"using params {analysis_params}")
        if analysis_params is None:
            analysis_params = {}
        eua = ana_func(process_uuid, process_df, analysis_params)
        # self.base.print_message("calculating analysis output")
        calc_result = eua.calc_output()
        if calc_result:
            # self.base.print_message("exporting analysis output")
            model_dict, output_dict = eua.export_analysis(
                bucket=self.bucket,
                region=self.region,
                dummy=self.world_config.get("dummy", True),
            )
            process_dict = pgs3.LOADER.get_prc(process_uuid, hmod=False)
            if process_dict.get("data_request_id", None) is not None:
                model_dict["data_request_id"] = process_dict["data_request_id"]
            ana_tsstr = model_dict.get(
                "analysis_timestamp", set_time().strftime("%Y-%m-%d %H:%M:%S.%f")
            )
            ana_ts = datetime.strptime(ana_tsstr, "%Y-%m-%d %H:%M:%S.%f")
            HMS = ana_ts.strftime("%H%M%S")
            year_week = ana_ts.strftime("%y.%U")
            analysis_day = ana_ts.strftime("%Y%m%d")
            local_ana_dir = os.path.join(
                self.local_ana_root, year_week, analysis_day, f"{HMS}__{eua.analysis_name}"
            )
            os.makedirs(local_ana_dir, exist_ok=True)
            with open(
                os.path.join(local_ana_dir, f"{eua.analysis_uuid}.yml"), "w"
            ) as f:
                f.write(yml_dumps(model_dict))

            s3_model_target = f"analysis/{eua.analysis_uuid}.json"

            if not self.config_dict.get("local_only", False):
                self.base.print_message("uploading analysis model to S3 bucket")
                try:
                    s3_model_success = await self.to_s3(model_dict, s3_model_target)
                except Exception as e:
                    tb = "".join(
                        traceback.format_exception(type(e), e, e.__traceback__)
                    )
                    print(tb)
            else:
                s3_model_success = True
                self.base.print_message(
                    "Analysis server config set to local_only, skipping S3/API push."
                )

            outputs = model_dict.get("outputs", [])
            output_successes = []
            # self.base.print_message("uploading analysis outputs to S3 bucket")
            for output in outputs:
                s3_dict_keys = output["output_keys"]
                s3_dict = {k: v for k, v in output_dict.items() if k in s3_dict_keys}
                s3_output_target = output["analysis_output_path"]["key"]
                local_json_out = os.path.join(
                    local_ana_dir, os.path.basename(s3_output_target)
                )
                # with gzip.open(local_json_out, "wt", encoding="utf-8") as f:
                os.makedirs(os.path.dirname(local_json_out), exist_ok=True)
                with open(local_json_out, "w") as f:
                    json.dump(s3_dict, f)
                if not self.config_dict.get("local_only", False):
                    s3_success = await self.to_s3(
                        s3_dict, s3_output_target, compress=False
                    )
                else:
                    s3_success = True
                output_successes.append(s3_success)
            s3_output_success = all(output_successes)

            # api_success = await self.to_api(model_dict)
            api_success = True

            if s3_model_success and s3_output_success and api_success:
                self.base.print_message(f"Successfully synced {eua.analysis_uuid}")
                return True

        self.base.print_message(
            f"Analysis {eua.analysis_uuid} sync failed for process_uuid {process_uuid}.",
            warning=True,
        )
        self.running_tasks.pop(str(process_uuid))
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
        recent: bool = True,
    ):
        """Generate list of EcheUvisAnalysis from sequence or plate_id (latest seq)."""
        # eul = EcheUvisLoader(env_file=self.config_dict["env_file"], cache_s3=True)
        # min_date = datetime.now().strftime("%Y-%m-%d") if recent else "2024-01-01"
        plate_filter = f"    AND (hs.sequence_params->>'plate_id')::numeric = {plate_id}"
        df = pgs3.LOADER.get_sequence(
            query=SDCUVIS_QUERY+plate_filter, sequence_uuid=str(sequence_uuid)
        )

        ## patch erroneous plate_ids here
        idxs = df.query("sequence_label.str.startswith('ZnSbO') & plate_id==4014").index
        df.loc[idxs, "global_label"] = df.loc[idxs].global_label.str.replace(
            "solid__4014", "solid__2300"
        )
        df.loc[idxs, "plate_id"] = 2300

        # all processes in sequence
        pdf = df.sort_values(
            ["sequence_timestamp", "process_timestamp"], ascending=False
        )
        pdf = pdf.query("sequence_name.str.startswith('ECHEUVIS')")
        if sequence_uuid is not None:
            pdf = pdf.query("sequence_uuid==@sequence_uuid")
        pdf = pdf.query("sequence_timestamp==sequence_timestamp.max()").sort_values(
            "process_timestamp"
        )
        # only SPEC actions during CA
        eudf = (
            pdf.query("experiment_name=='ECHEUVIS_sub_CA_led'")
            .query("run_use=='data'")
            .query("action_name=='acquire_spec_extrig'")
            # .query("action_name=='acquire_spec_adv'")
        )
        for puuid in eudf.process_uuid:
            await self.enqueue_calc(
                (
                    puuid,
                    pdf,
                    params,
                    EcheUvisAnalysis,
                )
            )

    async def batch_calc_dryuvis(
        self,
        plate_id: Optional[int] = None,
        sequence_uuid: Optional[UUID] = None,
        params: dict = {},
        recent: bool = True,
    ):
        """Generate list of DryUvisAnalysis from sequence or plate_id (latest seq)."""
        # eul = EcheUvisLoader(env_file=self.config_dict["env_file"], cache_s3=True)
        min_date = datetime.now().strftime("%Y-%m-%d") if recent else "2023-04-26"

        df = pgs3.LOADER.get_recent(
            query=DRYUVIS_QUERY, min_date=min_date, plate_id=plate_id
        )

        retry_counter = 0
        while df.shape[0] == 0 and retry_counter < 3:
            self.base.print_message(
                "query returned 0 rows, checking again in 5 seconds."
            )
            time.sleep(5)
            df = pgs3.LOADER.get_recent(
                query=DRYUVIS_QUERY, min_date=min_date, plate_id=plate_id
            )
            retry_counter += 1

        # all processes in sequence
        pdf = df.sort_values(
            ["sequence_timestamp", "process_timestamp"], ascending=False
        )
        pdf = pdf.query("sequence_name.str.startswith('UVIS')")
        if sequence_uuid is not None:
            pdf = pdf.query("sequence_uuid==@sequence_uuid")
        pdf = pdf.query("sequence_timestamp==sequence_timestamp.max()")

        udf = (
            pdf.query("experiment_name=='UVIS_sub_measure'")
            .query("run_use=='data'")
            .query("action_name=='acquire_spec_adv'")
        )
        for puuid in udf.process_uuid:
            await self.enqueue_calc(
                (
                    puuid,
                    pdf,
                    params,
                    DryUvisAnalysis,
                )
            )

    async def batch_calc_icpms_local(
        self,
        sequence_zip_path: str = "",
        params: dict = {},
    ):
        """Generate list of IcpmsAnalysis from sequence."""
        local_loader = LocalLoader(sequence_zip_path)
        pdf = local_loader.processes

        for puuid in pdf.process_uuid:
            await self.enqueue_calc(
                (
                    puuid,
                    local_loader,
                    params,
                    IcpmsAnalysis,
                )
            )

    def shutdown(self):
        pass
