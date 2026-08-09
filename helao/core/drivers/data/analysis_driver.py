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
analysis_params)``. Which ``<deployment>`` that is comes from
:func:`resolve_analyses_package`, which survives a hexagon graft (see its
docstring); a configured analysis that cannot be loaded raises
:class:`AnalysisLoadError` rather than leaving the server short a route.
"""

__all__ = [
    "AnalysisSyncer",
    "AnalysisExecutor",
    "AnalysisLoadError",
    "load_analysis_classes",
    "make_analysis_app",
    "resolve_analyses_package",
]

import asyncio
import inspect
import os
from importlib import import_module, util as importlib_util
from typing import Optional
from uuid import UUID

from helao.core.drivers.data.analyses.base_analysis import BaseAnalysis
from helao.core.drivers.data.analysis_layout import (
    analysis_dir,
    analysis_root,
    analysis_suffix,
    parse_analysis_timestamp,
    publish_outputs,
    sequence_part_of,
    write_model_yml,
)
from helao.core.drivers.data.loaders import pgs3
from helao.core.drivers.data.loaders.localfs import LocalLoader
from helao.core.drivers.data.sync_driver import HelaoSyncer
from helao.core.error import ErrorCodes
from helao.core.servers.base import Base
from helao.core.servers.base_api import BaseAPI
from helao.helpers import config_loader
from helao.helpers import helao_logging as logging
from helao.helpers.executor import Executor

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

# metadata keys copied from the source process onto the analysis model when present
_PROCESS_METADATA_KEYS = (
    "data_request_id",
    "campaign_uuid",
    "campaign_name",
    "run_id",
)


class AnalysisLoadError(RuntimeError):
    """A configured ``params.analyses`` entry could not be loaded.

    Raised at app-build time (before the server binds its port) so a bad
    ``analyses`` list aborts the analysis server instead of starting it with
    ``analyze_*`` routes silently missing.
    """


#: Subpackage, under a deployment, that holds its analysis modules.
_ANALYSES_SUBPKG = "drivers.data.analyses"


def _analyses_package(deployment: str) -> str:
    """Return the analyses package path for ``deployment``."""
    return f"helao.deploy.{deployment}.{_ANALYSES_SUBPKG}"


def _deployment_of_module(module_path: Optional[str]) -> Optional[str]:
    """Return the deployment owning a ``helao.deploy.<dep>...`` module path."""
    parts = (module_path or "").split(".")
    if len(parts) > 2 and parts[0] == "helao" and parts[1] == "deploy":
        return parts[2] or None
    return None


def _deployment_of_config(config_path: Optional[str]) -> Optional[str]:
    """Return the deployment owning ``helao/deploy/<dep>/configs/<name>.yml``."""
    if not config_path:
        return None
    dep_dir = os.path.dirname(os.path.dirname(os.path.abspath(config_path)))
    if os.path.basename(os.path.dirname(dep_dir)) != "deploy":
        return None
    return os.path.basename(dep_dir) or None


def _package_importable(package: str) -> bool:
    """Whether ``package`` can be located without importing it."""
    try:
        return importlib_util.find_spec(package) is not None
    except Exception:
        # A missing parent package raises rather than returning None.
        return False


def resolve_analyses_package(
    deployment: Optional[str],
    legacy_module: Optional[str] = None,
    config_path: Optional[str] = None,
) -> Optional[str]:
    """Return the package to import this server's analysis modules from.

    ``world_cfg["deployment"]`` alone is not enough: ``fast_launcher`` sets it
    from the server's OWN ``deployment:`` value, so a server grafted onto the
    hexagon composition (``deployment: hexagon``) would look for its analyses
    under ``helao.deploy.hexagon.drivers.data.analyses``, which does not exist
    — the graft would lose every ``analyze_*`` route. The graft nevertheless
    carries the information, in two shapes, so candidates are tried in order:

    1. the deployment owning ``legacy_module`` (the ``fast: graft`` shape, where
       the config names the wrapped legacy module outright),
    2. ``deployment`` — what this resolved to before, and what every
       un-grafted server resolves to,
    3. the deployment owning the loaded config file (the hardcoded-shim shape,
       ``fast: <name>`` + ``deployment: hexagon``, where no ``legacy_module:``
       key exists to read).

    Each candidate must name an importable package to be chosen, which is what
    keeps this backwards compatible: whenever the previous behaviour resolved a
    package that exists, candidate 2 wins and the result is identical. The
    order only takes effect where the old resolution imported nothing at all.

    Returns the chosen package, or — when no candidate is importable — the
    package ``deployment`` names, so the caller's error reports what was
    configured. Returns ``None`` only when there is no deployment at all.
    """
    candidates = []
    for candidate in (
        _deployment_of_module(legacy_module),
        deployment,
        _deployment_of_config(config_path),
    ):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    for candidate in candidates:
        package = _analyses_package(candidate)
        if _package_importable(package):
            if candidate != deployment:
                LOGGER.info(
                    f"Analyses package resolved to '{package}' (deployment "
                    f"'{deployment}' has none); candidates tried: {candidates}."
                )
            return package
    return _analyses_package(deployment) if deployment else None


def _resolve_analysis_class(module, module_name: str, class_name: str):
    """Return the configured :class:`BaseAnalysis` subclass from ``module``.

    When ``class_name`` is given it is looked up directly; otherwise the module
    is scanned for the single :class:`BaseAnalysis` subclass defined in it.

    Raises:
        AnalysisLoadError: when no single valid class can be identified.
    """
    if class_name:
        ana_cls = getattr(module, class_name, None)
        if ana_cls is None or not (
            inspect.isclass(ana_cls) and issubclass(ana_cls, BaseAnalysis)
        ):
            raise AnalysisLoadError(
                f"'{class_name}' in '{module_name}' is not a BaseAnalysis subclass."
            )
        return ana_cls
    candidates = [
        obj
        for _, obj in inspect.getmembers(module, inspect.isclass)
        if issubclass(obj, BaseAnalysis)
        and obj is not BaseAnalysis
        and obj.__module__ == module.__name__
    ]
    if not candidates:
        raise AnalysisLoadError(f"No BaseAnalysis subclass found in '{module_name}'.")
    if len(candidates) > 1:
        raise AnalysisLoadError(
            f"Multiple BaseAnalysis subclasses found in '{module_name}': "
            f"{[c.__name__ for c in candidates]}. Specify 'module:ClassName' "
            "in config."
        )
    return candidates[0]


def load_analysis_classes(
    analyses,
    deployment: Optional[str],
    legacy_module: Optional[str] = None,
    config_path: Optional[str] = None,
) -> dict:
    """Import and map the analysis classes named in an ``analyses`` config list.

    Each entry is either a module name (e.g. ``"icpms_local"``) or an explicit
    ``"module:ClassName"``. Modules are imported from the package
    :func:`resolve_analyses_package` picks, and the resolved
    :class:`BaseAnalysis` subclass is mapped to the endpoint name
    ``analyze_<module>``.

    Every configured entry must load. A miss used to be logged and skipped,
    which let a server start clean with its ``analyze_*`` routes missing —
    discovered only when an orchestrator dispatched to one mid-run and got a
    404. Misses are still logged individually (so the log names each one), then
    reported together as a single :class:`AnalysisLoadError`.

    Args:
        analyses: Iterable of module/class specifiers from the server config.
        deployment: Deployment name from the world config.
        legacy_module: This server's ``legacy_module:`` value, when it is a
            hexagon graft.
        config_path: Path of the loaded config file.

    Returns:
        Mapping from endpoint name (``analyze_<module>``) to analysis class.

    Raises:
        AnalysisLoadError: when any configured analysis cannot be loaded, or
            when analyses are configured but no deployment is known.
    """
    requested = list(analyses or [])
    if not requested:
        return {}
    base_pkg = resolve_analyses_package(deployment, legacy_module, config_path)
    if base_pkg is None:
        raise AnalysisLoadError(
            "No 'deployment' set in world config; cannot load the configured "
            f"analyses {requested}."
        )
    loaded = {}
    failures = []
    for entry in requested:
        module_name, _, class_name = entry.partition(":")
        try:
            module = import_module(f"{base_pkg}.{module_name}")
        except Exception as exc:
            LOGGER.error(
                f"Failed to import analysis module '{module_name}' from {base_pkg}.",
                exc_info=True,
            )
            failures.append(
                f"'{entry}': import of '{base_pkg}.{module_name}' failed "
                f"({type(exc).__name__}: {exc})"
            )
            continue
        try:
            ana_cls = _resolve_analysis_class(module, module_name, class_name)
        except AnalysisLoadError as exc:
            LOGGER.error(str(exc))
            failures.append(f"'{entry}': {exc}")
            continue
        endpoint_name = f"analyze_{module_name}"
        loaded[endpoint_name] = ana_cls
        LOGGER.info(
            f"Loaded analysis class {ana_cls.__name__} as endpoint '{endpoint_name}'."
        )
    if failures:
        raise AnalysisLoadError(
            f"{len(failures)} of {len(requested)} configured analyses could not "
            f"be loaded from '{base_pkg}': "
            + "; ".join(failures)
            + ". Fix the server config's params.analyses list (or the analysis "
            "module itself) — starting without these analyze_* routes would "
            "fail later, at dispatch, instead of now."
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
        self.local_ana_root = analysis_root(self.world_config["root"])
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
        calc_tup: tuple[UUID, LocalLoader, dict, BaseAnalysis, Optional[UUID]],
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

    def _calc_and_write_model(
        self,
        calc_tup: tuple[UUID, LocalLoader, dict, BaseAnalysis, Optional[UUID]],
    ) -> tuple:
        """Run one analysis and write its model yml. Synchronous -- run in a thread.

        This is the blocking half of :meth:`sync_ana`, split out so it can be
        handed to :func:`asyncio.to_thread` instead of being executed on the
        server's event loop.

        Args:
            calc_tup: Analysis tuple as accepted by :meth:`enqueue_calc`.

        Returns:
            ``(eua, model_dict, output_dict, local_ana_dir)``. When
            ``calc_output`` reports failure, ``model_dict``/``output_dict``/
            ``local_ana_dir`` are ``None`` and only ``eua`` is meaningful (the
            caller logs its uuid).
        """
        process_uuid, data_loader, analysis_params, ana_func, action_uuid = calc_tup
        if analysis_params is None:
            analysis_params = {}
        eua = ana_func(process_uuid, data_loader, analysis_params)
        if not eua.calc_output():
            return eua, None, None, None

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
        # Layout grammar lives in analysis_layout, shared verbatim with the
        # AnalysisArtifactPort adapter a post-hoc converter publishes through
        # (spec §5 row 13: one writer). The stamp passed here is each analysis's
        # own, which is what this server has always written -- see the module's
        # note on why the choice of stamp is an argument.
        first_action_dir = process_dict["dispatched_actions_abbr"][0][
            "action_output_dir"
        ]
        local_ana_dir = analysis_dir(
            self.local_ana_root,
            parse_analysis_timestamp(model_dict),
            eua.analysis_name,
            analysis_suffix(
                sequence_part_of(first_action_dir),
                model_dict.get("global_sample_label", ""),
            ),
        )
        write_model_yml(local_ana_dir, eua.analysis_uuid, model_dict)

        return eua, model_dict, output_dict, local_ana_dir

    async def sync_ana(
        self,
        calc_tup: tuple[UUID, LocalLoader, dict, BaseAnalysis, Optional[UUID]],
        retries: int = 3,
    ) -> bool:
        """Run one analysis and push its model and outputs to disk and S3.

        Instantiates the analysis class, calls ``calc_output`` then
        ``export_analysis``, attaches sequence/campaign metadata pulled from the
        corresponding process, writes the YAML model and JSON outputs under
        ``local_ana_root/<yy.ww>/<mmdd>/<HHMMSS>__<name>``, and uploads them to S3
        unless ``local_only`` is set.

        The blocking portion runs in a worker thread (see
        :meth:`_calc_and_write_model`), so several ``syncer`` workers genuinely
        overlap and the server's event loop stays responsive while an analysis
        is in flight. Only the S3 uploads are awaited on the loop itself.

        Args:
            calc_tup: Analysis tuple as accepted by :meth:`enqueue_calc`.
            retries: Number of retry attempts available for downstream uploads.
                Unused for this method's own logic but kept for signature symmetry.

        Returns:
            ``True`` when the analysis and all uploads succeed, otherwise ``False``.
        """
        process_uuid = calc_tup[0]
        # The analysis proper -- instantiation, calc_output, export_analysis, the
        # process metadata fetch and the model yml write -- is synchronous and
        # takes seconds, with no await point anywhere in it. Running it inline
        # pinned the server's event loop for its entire duration (measured: a
        # 24-analysis batch stalled the loop for the full 8.3s), so the
        # ``max_tasks`` workers overlapped nothing at all and the server could
        # not answer status or dispatch requests meanwhile. The work is
        # dominated by numpy/pandas and zip/S3 reads, all of which release the
        # GIL, so a thread recovers real concurrency: 3.54x on 4 workers.
        eua, model_dict, output_dict, local_ana_dir = await asyncio.to_thread(
            self._calc_and_write_model, calc_tup
        )
        if model_dict is not None:
            # `local_only` is expressed as "no uploader", which is what
            # publish_outputs gates BOTH the model body and every output group
            # on -- one switch, no way to leave one of the two ungated.
            uploader = None if self.config_dict.get("local_only", False) else self.to_s3
            if await publish_outputs(
                model_dict, output_dict, local_ana_dir, uploader=uploader
            ):
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
    event, so it cannot be queried here). The server's ``legacy_module:`` and
    the loaded config's path go to :func:`resolve_analyses_package` alongside
    the world deployment, so a hexagon-grafted server still finds its own
    deployment's analyses.

    Args:
        server_key: Key identifying this server in the orchestration group.

    Returns:
        The configured :class:`BaseAPI` application.

    Raises:
        AnalysisLoadError: when a configured analysis cannot be loaded; the
            server aborts rather than starting without that endpoint.
    """
    world_cfg = config_loader.CONFIG or {}
    server_cfg = world_cfg.get("servers", {}).get(server_key, {})
    analyses = server_cfg.get("params", {}).get("analyses", [])
    analysis_classes = load_analysis_classes(
        analyses,
        world_cfg.get("deployment"),
        legacy_module=server_cfg.get("legacy_module"),
        config_path=world_cfg.get("loaded_config_path"),
    )

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
    # Both ``app.base`` and ``app.driver`` are created in BaseAPI's own startup
    # event, so wire the hook from a startup handler (registered after
    # BaseAPI's, hence run after it). The hook still reads app.driver lazily.
    @app.on_event("startup")
    def _wire_hotreload_busy():
        app.base.hotreload_busy_hook = lambda: (
            app.driver is not None and app.driver.has_pending_work()
        )

    return app
