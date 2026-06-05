"""Driver that runs HELAO analyses and uploads results to S3.

Provides :class:`HelaoAnalysisSyncer`, a :class:`HelaoSyncer` subclass that
maintains a queue of analysis tuples (process UUID, query DataFrame,
parameters, analysis class, and parent action UUID), runs each analysis
in parallel worker coroutines, writes the resulting model and outputs to
the local analyses tree, and (unless ``local_only`` is set) uploads them
to S3 and optionally to the Modelyst API. Also defines
:class:`LocalAnalysisExecutor`, an :class:`Executor` that loads a local
sequence zip and enqueues one analysis per contained process.
"""

__all__ = ["HelaoAnalysisSyncer"]

from helao.helpers import helao_logging as logging

import time
import asyncio
import os
from datetime import datetime
from typing import Optional, Tuple
from uuid import UUID

import aiohttp
import json
import pandas as pd

from helao.core.servers.base import Base
from helao.helpers.time_utils import set_time
from helao.helpers.yml_tools import yml_dumps
from helao.helpers.executor import Executor
from helao.core.error import ErrorCodes
from helao.core.drivers.data.sync_driver import HelaoSyncer
from helao.core.drivers.data.analyses.base_analysis import BaseAnalysis
from helao.core.drivers.data.loaders import pgs3
from helao.core.drivers.data.loaders.localfs import LocalLoader
from ...drivers.data.analyses.echeuvis_stability import (
    EcheUvisAnalysis,
    SDCUVIS_QUERY,
)
from ...drivers.data.analyses.uvis_bkgsubnorm import DryUvisAnalysis, DRYUVIS_QUERY
from ...drivers.data.analyses.icpms_local import IcpmsAnalysis
from ...drivers.data.analyses.xrfs_local import XrfsAnalysis

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


class HelaoAnalysisSyncer(HelaoSyncer):
    """Queue-based worker that runs analyses and syncs outputs to S3/API.

    Pulls ``(process_uuid, query_df, params, analysis_class,
    analysis_action_uuid)`` tuples from an ``asyncio.Queue``, instantiates
    the analysis class, exports the resulting model and outputs to the
    local ANALYSES tree, and (when not running in ``local_only`` mode)
    uploads them to the configured S3 bucket. ``max_tasks`` worker
    coroutines run in parallel.

    Attributes:
        base: Owning action server.
        running_tasks: Mapping from process UUID string to the worker
            asyncio.Task currently processing it.
        config_dict: ``params`` block from the server config.
        world_config: Full world config dict.
        local_ana_root: Local ``ANALYSES`` root path.
        max_tasks: Number of concurrent worker coroutines.
        task_queue: FIFO queue of pending analysis tuples.
        task_set: Set of enqueued process UUIDs used to deduplicate.
        syncer_loops: Mapping from worker index to its
            :class:`asyncio.Task`.
        s3: S3 client from the shared ``pgs3`` loader.
        s3r: S3 resource from the shared ``pgs3`` loader.
        bucket: S3 bucket name.
        region: S3 region.
    """

    base: Base
    running_tasks: dict

    def __init__(self, action_serv: Base):
        """Initialise queues, loader, and worker coroutines.

        Args:
            action_serv: Hosting action server, used for its
                ``server_cfg`` ``params`` and the ``world_cfg``.
        """
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.world_config = action_serv.world_cfg
        self.config_dict["env_file"] = self.world_config["helao_credentials_path"]
        self.local_ana_root = os.path.join(self.world_config["root"], "ANALYSES")
        self.max_tasks = self.config_dict.get("max_tasks", 1)
        # declare global loader for analysis models used by driver.batch_* methods
        self.get_loader()
        # self.api_host = self.config_dict["api_host"]

        self.task_queue = asyncio.Queue()
        self.task_set = set()
        self.running_tasks = {}

        self.syncer_loops = {
            i: asyncio.create_task(self.syncer(), name=f"syncer_loop__{i}")
            for i in range(self.max_tasks)
        }

    def get_loader(self):
        """Install the shared :class:`pgs3.EcheUvisLoader` and cache its handles.

        Populates ``pgs3.LOADER`` so that ``batch_calc_*`` and analysis
        classes share one configured loader, then stores its S3 client,
        resource, bucket and region on ``self``.
        """
        pgs3.LOADER = pgs3.EcheUvisLoader(
            self.config_dict["env_file"],
            cache_s3=False,
            cache_json=False,
            cache_sql=False,
        )
        self.s3 = pgs3.LOADER.cli
        self.s3r = pgs3.LOADER.res
        # os.environ["AWS_CONFIG_PATH"] = self.config_dict["aws_config_path"]
        # self.aws_session = boto3.Session(profile_name=self.config_dict["aws_profile"])
        # self.s3 = self.aws_session.client("s3")
        self.bucket = pgs3.LOADER.s3_bucket
        self.region = pgs3.LOADER.s3_region

    def sync_exit_callback(self, task: asyncio.Task):
        """Drop the completed ``task`` from ``running_tasks`` and ``task_set``.

        Args:
            task: The completed :class:`asyncio.Task` whose name is used
                as the lookup key.
        """
        task_name = task.get_name()
        if task_name in self.running_tasks:
            self.running_tasks.pop(task_name)
            try:
                self.task_set.remove(task_name)
            except KeyError:
                pass

    async def enqueue_calc(
        self,
        calc_tup: Tuple[UUID, pd.DataFrame, dict, BaseAnalysis, Optional[UUID]],
    ):
        """Push a single analysis tuple onto :attr:`task_queue`.

        Args:
            calc_tup: ``(process_uuid, query_df, ana_params,
                analysis_class, analysis_action_uuid)`` describing one
                analysis to run.
        """
        self.task_set.add(calc_tup[0])
        await self.task_queue.put(calc_tup)
        LOGGER.info(f"Added {str(calc_tup[0])} to syncer queue.")

    async def syncer(self):
        """Worker coroutine: pull one analysis tuple from the queue and await its sync.

        ``self.max_tasks`` instances run as parallel workers so up to ``max_tasks``
        analyses can sync concurrently. Each worker owns one calc tuple at a time
        and the worker count is the only concurrency bound.
        """
        LOGGER.info("Starting syncer queue processor task.")
        while True:
            calc_tup = await self.task_queue.get()
            proc_uuid_str = str(calc_tup[0])
            LOGGER.info(f"creating ana task for {calc_tup[0]}.")
            if proc_uuid_str in self.running_tasks:
                LOGGER.debug(
                    f"{proc_uuid_str} ana sync is already in progress, skipping."
                )
                self.task_queue.task_done()
                continue
            self.running_tasks[proc_uuid_str] = asyncio.current_task()
            try:
                await self.sync_ana(calc_tup)
            except Exception:
                LOGGER.error(
                    f"Error in ana syncer worker for {proc_uuid_str}", exc_info=True
                )
            finally:
                self.running_tasks.pop(proc_uuid_str, None)
                self.task_set.discard(calc_tup[0])
                self.task_queue.task_done()

    async def sync_ana(
        self,
        calc_tup: Tuple[UUID, pd.DataFrame, dict, BaseAnalysis, UUID],
        retries: int = 3,
    ) -> bool:
        """Run one analysis and push its model and outputs to disk and S3.

        Instantiates the analysis class, calls ``calc_output`` then
        ``export_analysis``, attaches sequence/campaign metadata pulled
        from the corresponding process, writes the YAML model and JSON
        outputs under ``local_ana_root/<yy.ww>/<mmdd>/<HHMMSS>__<name>``,
        and uploads them to S3 unless ``local_only`` is set.

        Args:
            calc_tup: Analysis tuple as accepted by :meth:`enqueue_calc`.
            retries: Number of retry attempts available for downstream
                uploads. Unused for this method's own logic but kept for
                signature symmetry.

        Returns:
            ``True`` when the analysis and all uploads succeed,
            otherwise ``False``.
        """
        process_uuid, process_df, analysis_params, ana_func, action_uuid = calc_tup
        # LOGGER.info(f"performing analysis {analysis_name}")
        # LOGGER.info(f"using params {analysis_params}")
        if analysis_params is None:
            analysis_params = {}
        eua = ana_func(process_uuid, process_df, analysis_params)
        # LOGGER.info("calculating analysis output")
        calc_result = eua.calc_output()
        if calc_result:
            # LOGGER.info("exporting analysis output")
            model_dict, output_dict = eua.export_analysis(
                bucket=self.bucket,
                region=self.region,
                dummy=self.world_config.get("dummy", True),
            )
            model_dict["analysis_action_uuid"] = str(action_uuid)
            process_dict = pgs3.LOADER.get_prc(process_uuid, hmod=False)
            for pkey in ["data_request_id", "campaign_uuid", "campaign_name", "run_id"]:
                if process_dict.get(pkey, None) is not None:
                    model_dict[pkey] = process_dict[pkey]
            ana_tsstr = model_dict.get(
                "analysis_timestamp", set_time().strftime("%Y-%m-%d %H:%M:%S.%f")
            )
            ana_ts = datetime.strptime(ana_tsstr, "%Y-%m-%d %H:%M:%S.%f")
            HMS = ana_ts.strftime("%H%M%S")
            year_week = ana_ts.strftime("%y.%U")
            analysis_day = ana_ts.strftime("%m%d")
            analysis_suffix = ""
            gsl = model_dict.get("global_sample_label", "")
            first_action_dir = process_dict["dispatched_actions_abbr"][0][
                "action_output_dir"
            ]
            sequence_part = first_action_dir.split("/")[-3]
            if len(sequence_part.split("__")) == 3:
                sequence_label = sequence_part.split("__")[-1]
                analysis_suffix = f"__{sequence_label}"
            elif gsl.startswith("legacy__solid__"):
                plate_id = gsl.split("legacy__solid__")[-1].split("_")[0]
                checksum = sum([int(x) for x in plate_id]) % 10
                analysis_suffix = f"__{plate_id}{checksum}"
            local_ana_dir = os.path.join(
                self.local_ana_root,
                year_week,
                analysis_day,
                f"{HMS}__{eua.analysis_name}{analysis_suffix}",
            )
            os.makedirs(local_ana_dir, exist_ok=True)
            with open(
                os.path.join(local_ana_dir, f"{eua.analysis_uuid}.yml"), "w"
            ) as f:
                f.write(yml_dumps(model_dict))

            s3_model_target = f"analysis/{eua.analysis_uuid}.json"

            if not self.config_dict.get("local_only", False):
                LOGGER.info("uploading analysis model to S3 bucket")
                try:
                    s3_model_success = await self.to_s3(model_dict, s3_model_target)
                except Exception:
                    LOGGER.error(
                        f"Failed to upload analysis model {eua.analysis_uuid} to S3.",
                        exc_info=True,
                    )
            else:
                s3_model_success = True
                LOGGER.info(
                    "Analysis server config set to local_only, skipping S3/API push."
                )

            outputs = model_dict.get("outputs", [])
            output_successes = []
            # LOGGER.info("uploading analysis outputs to S3 bucket")
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

            api_success = True

            if s3_model_success and s3_output_success and api_success:
                LOGGER.info(f"Successfully synced {eua.analysis_uuid}")
                return True

        LOGGER.warning(
            f"Analysis {eua.analysis_uuid} sync failed for process_uuid {process_uuid}."
        )
        return False


    async def batch_calc_icpms_local(
        self,
        sequence_zip_path: str = "",
        params: dict = {},
        analysis_action_uuid: Optional[UUID] = None,
    ):
        """Enqueue :class:`IcpmsAnalysis` for each process in a local zip.

        Args:
            sequence_zip_path: Path to a sequence zip parseable by
                :class:`LocalLoader`.
            params: Per-analysis parameter overrides.
            analysis_action_uuid: UUID of the requesting action.
        """
        local_loader = LocalLoader(sequence_zip_path)
        pdf = local_loader.processes

        for puuid in pdf.process_uuid:
            await self.enqueue_calc(
                (
                    puuid,
                    local_loader,
                    params,
                    IcpmsAnalysis,
                    analysis_action_uuid,
                )
            )

    async def batch_calc_xrfs_local(
        self,
        sequence_zip_path: str = "",
        params: dict = {},
        analysis_action_uuid: Optional[UUID] = None,
    ):
        """Enqueue :class:`XrfsAnalysis` for each process in a local zip.

        Args:
            sequence_zip_path: Path to a sequence zip parseable by
                :class:`LocalLoader`.
            params: Per-analysis parameter overrides.
            analysis_action_uuid: UUID of the requesting action.
        """
        local_loader = LocalLoader(sequence_zip_path)
        pdf = local_loader.processes

        for puuid in pdf.process_uuid:
            await self.enqueue_calc(
                (
                    puuid,
                    local_loader,
                    params,
                    XrfsAnalysis,
                    analysis_action_uuid,
                )
            )

    def shutdown(self):
        """Hook for graceful shutdown (no-op)."""
        pass


class LocalAnalysisExecutor(Executor):
    """Executor that enqueues local analyses from a sequence zip.

    Reads the ``sequence_zip_path`` action parameter, builds a
    :class:`LocalLoader`, and enqueues one ``analysis_class`` task per
    process found in the loader onto the parent
    :class:`HelaoAnalysisSyncer`.
    """

    driver: HelaoAnalysisSyncer

    def __init__(self, analysis_class: BaseAnalysis, *args, **kwargs):
        """Capture executor context and the target analysis class.

        Args:
            analysis_class: :class:`BaseAnalysis` subclass to instantiate
                for each enqueued process.
            *args: Positional arguments for :class:`Executor`.
            **kwargs: Keyword arguments for :class:`Executor`.
        """
        super().__init__(*args, **kwargs)
        try:
            self.poll_rate = 0.1
            self.action_params = self.active.action.action_params
            self.driver = self.active.driver
            self.analysis_class = analysis_class
            LOGGER.info("Initialized LocalAnalysisExecutor.")
        except Exception:
            LOGGER.error("Failed to initialize LocalAnalysisExecutor.", exc_info=True)

    async def _pre_exec(self):
        """Build a :class:`LocalLoader` from the action's ``sequence_zip_path``."""
        try:
            self.loader = LocalLoader(self.action_params["sequence_zip_path"])
            LOGGER.info("Initialized LocalLoader in LocalAnalysisExecutor.")
            error = ErrorCodes.none
        except Exception:
            LOGGER.error("Failed to initialize LocalLoader.", exc_info=True)
            error = ErrorCodes.critical
        return {"error": error}

    async def _exec(self):
        """Enqueue one analysis tuple per process found in the loaded zip."""
        try:
            processes = self.loader.processes
            for puuid in processes.process_uuid:
                await self.driver.enqueue_calc(
                    (
                        puuid,
                        self.loader,
                        self.action_params.get("params", {}),
                        self.analysis_class,
                        self.active.action.action_uuid,
                    )
                )
            LOGGER.info("Enqueued all calculations in LocalAnalysisExecutor.")
            error = ErrorCodes.none
        except Exception:
            LOGGER.error("Failed to enqueue calculations.", exc_info=True)
            error = ErrorCodes.critical
        return {"error": error}
