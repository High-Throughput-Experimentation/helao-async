"""Data analysis driver

Handles Helao analyses uploads to S3.

"""

__all__ = ["HelaoAnalysisSyncer"]

import asyncio
import traceback
from copy import copy
from datetime import datetime
from pathlib import Path
from typing import Union, Optional, Tuple
from uuid import UUID

import aiohttp

import botocore.exceptions
import pandas as pd

from helao.servers.base import Base
from helao.drivers.data.sync_driver import dict2json
from helao.drivers.data.loaders import pgs3
from helao.drivers.data.analyses.echeuvis_stability import (
    EcheUvisAnalysis,
    SDCUVIS_QUERY,
)
from helao.drivers.data.analyses.uvis_bkgsubnorm import (
    DryUvisAnalysis,
    DRYUVIS_QUERY
)


class HelaoAnalysisSyncer:
    base: Base
    running_tasks: dict

    def __init__(self, action_serv: Base):
        """Pushes yml to S3 and API."""
        self.base = action_serv
        self.config_dict = action_serv.server_cfg["params"]
        self.world_config = action_serv.world_cfg
        self.max_tasks = self.config_dict.get("max_tasks", 4)
        # declare global loader for analysis models used by driver.batch_* methods
        pgs3.LOADER = pgs3.EcheUvisLoader(
            self.config_dict["env_file"],
            cache_s3=True,
            cache_json=True,
        )
        self.s3 = pgs3.LOADER.cli
        # os.environ["AWS_CONFIG_FILE"] = self.config_dict["aws_config_path"]
        # self.aws_session = boto3.Session(profile_name=self.config_dict["aws_profile"])
        # self.s3 = self.aws_session.client("s3")
        self.bucket = pgs3.LOADER.s3_bucket
        self.region = pgs3.LOADER.s3_region
        # self.api_host = self.config_dict["api_host"]

        self.task_queue = asyncio.PriorityQueue()
        self.task_set = set()
        self.running_tasks = {}

        self.syncer_loop = asyncio.create_task(self.syncer(), name="syncer_loop")
        self.ana_funcs = {
            "ECHEUVIS_InsituOpticalStability": EcheUvisAnalysis,
            "UVIS_BkgSubNorm": DryUvisAnalysis,
        }

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
        process_uuid, process_df, analysis_params, analysis_name = calc_tup
        # self.base.print_message(f"performing analysis {analysis_name}")
        # self.base.print_message(f"using params {analysis_params}")
        if analysis_params is None:
            analysis_params = {}
        eua = self.ana_funcs[analysis_name](process_uuid, process_df, analysis_params)
        # self.base.print_message("calculating analysis output")
        eua.calc_output()
        # self.base.print_message("exporting analysis output")
        model_dict, output_dict = eua.export_analysis(
            analysis_name=analysis_name,
            bucket=self.bucket,
            region=self.region,
            dummy=self.world_config.get("dummy", True)
        )
        s3_model_target = f"analysis/{eua.analysis_uuid}.json"

        # self.base.print_message("uploading analysis model to S3 bucket")
        try:
            s3_model_success = await self.to_s3(model_dict, s3_model_target)
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            print(tb)

        outputs = model_dict.get("outputs", [])
        output_successes = []
        # self.base.print_message("uploading analysis outputs to S3 bucket")
        for output in outputs:
            s3_dict_keys = output["output_keys"]
            s3_dict = {k: v for k, v in output_dict.items() if k in s3_dict_keys}
            s3_output_target = output["analysis_output_path"]["key"]
            s3_success = await self.to_s3(s3_dict, s3_output_target)
            output_successes.append(s3_success)
        s3_output_success = all(output_successes)

        # api_success = await self.to_api(model_dict)
        api_success = True

        if s3_model_success and s3_output_success and api_success:
            self.base.print_message(f"Successfully synced {eua.analysis_uuid}")
            return True

        self.base.print_message(f"Analysis {eua.analysis_uuid} sync failed.")
        self.running_tasks.pop(str(process_uuid))
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
        recent: bool = True,
    ):
        """Generate list of EcheUvisAnalysis from sequence or plate_id (latest seq)."""
        # eul = EcheUvisLoader(env_file=self.config_dict["env_file"], cache_s3=True)
        min_date = datetime.now().strftime("%Y-%m-%d") if recent else "2023-04-26"
        df = pgs3.LOADER.get_recent(
            query=SDCUVIS_QUERY, min_date=min_date, plate_id=plate_id
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
        )
        for puuid in eudf.process_uuid:
            await self.enqueue_calc(
                (
                    puuid,
                    pdf,
                    params,
                    "ECHEUVIS_InsituOpticalStability",
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
                    "UVIS_BkgSubNorm",
                )
            )

    def shutdown(self):
        pass


# for each EcheUvisAnalysis:
# populate HelaoAnalysis model
# write ana.outputs.json() to s3 bucket
# push HelaoAnalysis to API
