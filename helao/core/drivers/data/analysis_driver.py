"""Consolidated analysis driver, executor, and FastAPI app builder.

Provides a single :class:`AnalysisSyncer` (a :class:`HelaoSyncer` subclass) that
maintains a queue of analysis tuples, runs each analysis in parallel worker
coroutines, writes the resulting model and outputs to the local ANALYSES tree,
and (unless ``local_only`` is set) uploads them to S3. The set of analysis
classes a given server exposes is chosen at launch by the ``analyses`` list in
the server config ``params`` block; :func:`make_analysis_app` generates one
action endpoint per configured analysis.

This module replaces the previously duplicated per-deployment drivers
(``HelaoAnalysisSyncer`` / ``LocalAnalysisSyncer``). Analysis classes are loaded
dynamically from ``helao.deploy.<deployment>.drivers.data.analyses`` and must
follow the local-loader batch contract ``__init__(process_uuid, local_loader,
analysis_params)``.
"""

__all__ = ["AnalysisSyncer", "AnalysisExecutor", "make_analysis_app"]

from helao.helpers import helao_logging as logging

import asyncio
import inspect
import os
from datetime import datetime
from importlib import import_module
from typing import Optional, Tuple
from uuid import UUID

import json

from helao.core.servers.base import Base
from helao.core.servers.base_api import BaseAPI
from helao.helpers import config_loader
from helao.helpers.time_utils import set_time
from helao.helpers.yml_tools import yml_dumps
from helao.helpers.executor import Executor
from helao.core.error import ErrorCodes
from helao.core.drivers.data.sync_driver import HelaoSyncer
from helao.core.drivers.data.analyses.base_analysis import BaseAnalysis
from helao.core.drivers.data.loaders import pgs3
from helao.core.drivers.data.loaders.localfs import LocalLoader

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

# metadata keys copied from the source process onto the analysis model when present
_PROCESS_METADATA_KEYS = (
    "data_request_id",
    "campaign_uuid",
    "campaign_name",
    "run_id",
)


def _resolve_analysis_class(module, module_name: str, class_name: str):
    """Return the configured :class:`BaseAnalysis` subclass from ``module``.

    When ``class_name`` is given it is looked up directly; otherwise the module
    is scanned for the single :class:`BaseAnalysis` subclass defined in it.
    Returns ``None`` (after logging) when no valid class is found.
    """
    if class_name:
        ana_cls = getattr(module, class_name, None)
        if ana_cls is None or not (
            inspect.isclass(ana_cls) and issubclass(ana_cls, BaseAnalysis)
        ):
            LOGGER.error(
                f"'{class_name}' in '{module_name}' is not a BaseAnalysis "
                "subclass; skipping."
            )
            return None
        return ana_cls
    candidates = [
        obj
        for _, obj in inspect.getmembers(module, inspect.isclass)
        if issubclass(obj, BaseAnalysis)
        and obj is not BaseAnalysis
        and obj.__module__ == module.__name__
    ]
    if not candidates:
        LOGGER.error(f"No BaseAnalysis subclass found in '{module_name}'; skipping.")
        return None
    if len(candidates) > 1:
        LOGGER.error(
            f"Multiple BaseAnalysis subclasses found in '{module_name}': "
            f"{[c.__name__ for c in candidates]}. Specify 'module:ClassName' "
            "in config; skipping."
        )
        return None
    return candidates[0]


def load_analysis_classes(analyses, deployment: Optional[str]) -> dict:
    """Import and map the analysis classes named in an ``analyses`` config list.

    Each entry is either a module name (e.g. ``"icpms_local"``) or an explicit
    ``"module:ClassName"``. Modules are imported from
    ``helao.deploy.<deployment>.drivers.data.analyses`` and the resolved
    :class:`BaseAnalysis` subclass is mapped to the endpoint name
    ``analyze_<module>``. Entries that fail to import or do not resolve to a
    :class:`BaseAnalysis` subclass are logged and skipped.

    Args:
        analyses: Iterable of module/class specifiers from the server config.
        deployment: Deployment name used to locate the analyses package.

    Returns:
        Mapping from endpoint name (``analyze_<module>``) to analysis class.
    """
    if not deployment:
        LOGGER.error(
            "No 'deployment' set in world config; cannot load analysis classes."
        )
        return {}
    base_pkg = f"helao.deploy.{deployment}.drivers.data.analyses"
    loaded = {}
    for entry in analyses or []:
        module_name, _, class_name = entry.partition(":")
        try:
            module = import_module(f"{base_pkg}.{module_name}")
        except Exception:
            LOGGER.error(
                f"Failed to import analysis module '{module_name}' from {base_pkg}.",
                exc_info=True,
            )
            continue
        ana_cls = _resolve_analysis_class(module, module_name, class_name)
        if ana_cls is None:
            continue
        endpoint_name = f"analyze_{module_name}"
        loaded[endpoint_name] = ana_cls
        LOGGER.info(
            f"Loaded analysis class {ana_cls.__name__} as endpoint '{endpoint_name}'."
        )
    return loaded


class AnalysisSyncer(HelaoSyncer):
    """Queue-based worker that runs analyses and syncs outputs to S3.

    Pulls ``(process_uuid, data_loader, params, analysis_class,
    analysis_action_uuid)`` tuples from an ``asyncio.Queue``, instantiates the
    analysis class, exports the resulting model and outputs to the local
    ANALYSES tree, and (when not running in ``local_only`` mode) uploads them to
    the configured S3 bucket. ``max_tasks`` worker coroutines run in parallel.

    The analysis class to run is passed per call (via :meth:`batch_calc`); the
    set of classes a server exposes as endpoints is resolved by
    :func:`make_analysis_app` from the server config ``params.analyses`` list.

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
        running_tasks: Mapping from process UUID string to worker task.
        syncer_loops: Mapping from worker index to its asyncio.Task.
        loader: S3/metadata loader shared with analysis classes via ``pgs3.LOADER``.
        s3: S3 client from the loader.
        s3r: S3 resource from the loader.
        bucket: S3 bucket name.
        region: S3 region.
    """

    base: Base
    running_tasks: dict

    def __init__(self, action_serv: Base):
        """Initialise queues, loader, configured analyses, and worker coroutines.

        Args:
            action_serv: Hosting action server, used for its ``server_cfg``
                ``params`` and the ``world_cfg``.
        """
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.world_config = action_serv.world_cfg
        self.env_file = (
            self.config_dict.get("env_file")
            or self.world_config.get("helao_credentials_path")
            or os.environ.get("HELAO_CREDENTIALS", "thisfiledoesntexist.env")
        )
        self.config_dict["env_file"] = self.env_file
        self.local_ana_root = os.path.join(self.world_config["root"], "ANALYSES")
        self.max_tasks = self.config_dict.get("max_tasks", 1)
        # declare global loader for analysis models used by driver.batch_calc
        self.get_loader()

        self.task_queue = asyncio.Queue()
        self.task_set = set()
        self.running_tasks = {}

        self.syncer_loops = {
            i: asyncio.create_task(self.syncer(), name=f"syncer_loop__{i}")
            for i in range(self.max_tasks)
        }

    def has_pending_work(self) -> bool:
        """True while any analysis is queued for or actively running.

        Consulted by the server's ``/hotreload_busy`` hook so the hot-reload
        watcher will not restart the analysis server mid-flight -- action
        servers get no ``--restore``, so a restart would drop the in-memory
        queue. ``task_set`` covers both queued and running process UUIDs.
        """
        return bool(self.task_set) or bool(self.running_tasks)

    def get_loader(self):
        """Install the shared :class:`pgs3.EcheUvisLoader` and cache its handles.

        Populates ``pgs3.LOADER`` so that :meth:`batch_calc` and analysis classes
        share one configured loader, then stores its S3 client, resource, bucket
        and region on ``self``.
        """
        pgs3.LOADER = pgs3.EcheUvisLoader(
            self.env_file,
            cache_s3=False,
            cache_json=False,
            cache_sql=False,
        )
        self.loader = pgs3.LOADER
        self.s3 = self.loader.cli
        self.s3r = self.loader.res
        self.bucket = self.loader.s3_bucket
        self.region = self.loader.s3_region

    def sync_exit_callback(self, task: asyncio.Task):
        """Drop the completed ``task`` from ``running_tasks`` and ``task_set``.

        Args:
            task: The completed :class:`asyncio.Task` whose name is used as the
                lookup key.
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
        calc_tup: Tuple[UUID, LocalLoader, dict, BaseAnalysis, Optional[UUID]],
    ):
        """Push a single analysis tuple onto :attr:`task_queue`.

        Args:
            calc_tup: ``(process_uuid, data_loader, ana_params, analysis_class,
                analysis_action_uuid)`` describing one analysis to run.
        """
        self.task_set.add(calc_tup[0])
        await self.task_queue.put(calc_tup)
        LOGGER.info(f"Added {str(calc_tup[0])} to syncer queue.")

    async def syncer(self):
        """Worker coroutine: pull one analysis tuple from the queue and await its sync.

        ``self.max_tasks`` instances run as parallel workers so up to
        ``max_tasks`` analyses can sync concurrently. Each worker owns one calc
        tuple at a time and the worker count is the only concurrency bound.
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
                LOGGER.alert(
                    f"Error in ana syncer worker for {proc_uuid_str}", exc_info=True
                )
            finally:
                self.running_tasks.pop(proc_uuid_str, None)
                self.task_set.discard(calc_tup[0])
                self.task_queue.task_done()

    async def sync_ana(
        self,
        calc_tup: Tuple[UUID, LocalLoader, dict, BaseAnalysis, Optional[UUID]],
        retries: int = 3,
    ) -> bool:
        """Run one analysis and push its model and outputs to disk and S3.

        Instantiates the analysis class, calls ``calc_output`` then
        ``export_analysis``, attaches sequence/campaign metadata pulled from the
        corresponding process, writes the YAML model and JSON outputs under
        ``local_ana_root/<yy.ww>/<mmdd>/<HHMMSS>__<name>``, and uploads them to S3
        unless ``local_only`` is set.

        Args:
            calc_tup: Analysis tuple as accepted by :meth:`enqueue_calc`.
            retries: Number of retry attempts available for downstream uploads.
                Unused for this method's own logic but kept for signature symmetry.

        Returns:
            ``True`` when the analysis and all uploads succeed, otherwise ``False``.
        """
        process_uuid, data_loader, analysis_params, ana_func, action_uuid = calc_tup
        if analysis_params is None:
            analysis_params = {}
        eua = ana_func(process_uuid, data_loader, analysis_params)
        calc_result = eua.calc_output()
        if calc_result:
            model_dict, output_dict = eua.export_analysis(
                bucket=self.bucket,
                region=self.region,
                dummy=self.world_config.get("dummy", True),
            )
            if action_uuid is not None:
                model_dict["analysis_action_uuid"] = str(action_uuid)
            process_dict = self.loader.get_prc(process_uuid, hmod=False)
            for pkey in _PROCESS_METADATA_KEYS:
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
            for output in outputs:
                s3_dict_keys = output["output_keys"]
                s3_dict = {k: v for k, v in output_dict.items() if k in s3_dict_keys}
                s3_output_target = output["analysis_output_path"]["key"]
                local_json_out = os.path.join(
                    local_ana_dir, os.path.basename(s3_output_target)
                )
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

    async def batch_calc(
        self,
        analysis_class: BaseAnalysis,
        sequence_zip_path: str = "",
        params: Optional[dict] = None,
        analysis_action_uuid: Optional[UUID] = None,
    ):
        """Enqueue ``analysis_class`` for each selected process in a local zip.

        Builds a :class:`LocalLoader` for ``sequence_zip_path``, asks the analysis
        class which process UUIDs it should run on (via
        :meth:`BaseAnalysis.select_process_uuids`), and enqueues one analysis
        tuple per process.

        Args:
            analysis_class: :class:`BaseAnalysis` subclass to instantiate.
            sequence_zip_path: Path to a sequence zip parseable by
                :class:`LocalLoader`.
            params: Per-analysis parameter overrides.
            analysis_action_uuid: UUID of the requesting action.
        """
        if params is None:
            params = {}
        local_loader = LocalLoader(sequence_zip_path)
        for puuid in analysis_class.select_process_uuids(local_loader):
            await self.enqueue_calc(
                (
                    puuid,
                    local_loader,
                    params,
                    analysis_class,
                    analysis_action_uuid,
                )
            )

    def shutdown(self):
        """Hook for graceful shutdown (no-op)."""
        pass


class AnalysisExecutor(Executor):
    """Executor that enqueues a local analysis from a sequence zip.

    Reads the ``sequence_zip_path`` and ``params`` action parameters and calls
    :meth:`AnalysisSyncer.batch_calc` for the bound ``analysis_class``, which
    enqueues one task per selected process.
    """

    driver: AnalysisSyncer

    def __init__(self, analysis_class: BaseAnalysis, *args, **kwargs):
        """Capture executor context and the target analysis class.

        Args:
            analysis_class: :class:`BaseAnalysis` subclass to instantiate for
                each enqueued process.
            *args: Positional arguments for :class:`Executor`.
            **kwargs: Keyword arguments for :class:`Executor`.
        """
        super().__init__(*args, **kwargs)
        try:
            self.poll_rate = 0.1
            self.action_params = self.active.action.action_params
            self.driver = self.active.driver
            self.analysis_class = analysis_class
            LOGGER.info("Initialized AnalysisExecutor.")
        except Exception:
            LOGGER.error("Failed to initialize AnalysisExecutor.", exc_info=True)

    async def _exec(self):
        """Enqueue analyses for all selected processes in the loaded zip."""
        try:
            await self.driver.batch_calc(
                self.analysis_class,
                sequence_zip_path=self.action_params["sequence_zip_path"],
                params=self.action_params.get("params", {}),
                analysis_action_uuid=self.active.action.action_uuid,
            )
            LOGGER.info("Enqueued all calculations in AnalysisExecutor.")
            error = ErrorCodes.none
        except Exception:
            LOGGER.error("Failed to enqueue calculations.", exc_info=True)
            error = ErrorCodes.critical
        return {"data": {}, "error": error}


def make_analysis_app(server_key) -> BaseAPI:
    """Build the analysis FastAPI app with config-driven action endpoints.

    Constructs a :class:`BaseAPI` backed by :class:`AnalysisSyncer` and registers
    one ``analyze_<module>`` action endpoint per analysis class named in the
    server config ``params.analyses`` list, plus the private ``list_running_tasks``
    and ``list_queued_tasks`` endpoints.

    The analysis classes are resolved from the global ``CONFIG`` at app-build
    time (the driver instance is not created until the FastAPI ``startup``
    event, so it cannot be queried here).

    Args:
        server_key: Key identifying this server in the orchestration group.

    Returns:
        The configured :class:`BaseAPI` application.
    """
    world_cfg = config_loader.CONFIG or {}
    server_cfg = world_cfg.get("servers", {}).get(server_key, {})
    analyses = server_cfg.get("params", {}).get("analyses", [])
    analysis_classes = load_analysis_classes(analyses, world_cfg.get("deployment"))

    app = BaseAPI(
        server_key=server_key,
        server_title=server_key,
        description="Analysis server",
        version=1.0,
        driver_classes=[AnalysisSyncer],
    )

    def _register_endpoint(endpoint_name: str, ana_cls: BaseAnalysis):
        """Register one analysis action endpoint bound to ``ana_cls``."""

        @app.post(f"/{server_key}/{endpoint_name}", tags=["action"], name=endpoint_name)
        async def _analyze(
            sequence_zip_path: str = "",
            params: dict = {},
        ):
            f"""Action endpoint: run {ana_cls.__name__} on a sequence zip."""
            active = await app.base.setup_and_contain_action()
            executor = AnalysisExecutor(
                analysis_class=ana_cls,
                active=active,
                oneoff=True,
                concurrent=True,
            )
            active_action_dict = active.start_executor(executor)
            return active_action_dict

        _analyze.__name__ = endpoint_name
        return _analyze

    for endpoint_name, ana_cls in analysis_classes.items():
        _register_endpoint(endpoint_name, ana_cls)

    @app.post("/list_running_tasks", tags=["private"])
    def list_current_tasks() -> list:
        """Return identifiers of analysis tasks currently executing in the syncer."""
        return list(app.driver.running_tasks.keys())

    @app.post("/list_queued_tasks", tags=["private"])
    def list_queued_tasks() -> list:
        """Return identifiers of analysis tasks queued but not yet running."""
        return list(app.driver.task_set)

    # Hot-reload safety: defer restart while an analysis is queued or running.
    # ``app.driver`` is not instantiated until the FastAPI startup event, so the
    # hook reads it lazily at call time (None -> not busy).
    app.base.hotreload_busy_hook = lambda: (
        app.driver is not None and app.driver.has_pending_work()
    )

    return app
