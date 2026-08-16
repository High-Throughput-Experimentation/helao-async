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

**A queued analysis outlives the process that queued it.** The queue itself
cannot: it is an ``asyncio.Queue`` of tuples holding a live
:class:`~helao.core.drivers.data.loaders.localfs.LocalLoader`, so it is neither
serialisable nor visible from outside the process, and the requesting action
returns as soon as it has enqueued -- its own record already reads *done*. A
restart therefore used to drop every queued analysis with no trace anywhere: no
file, no log line, and an action history claiming the work was requested
successfully. The fix is a **request journal**, one small json file per queued
analysis under ``<root>/STATES/ana_pending/``, written *before* the item reaches
the queue and deleted when its worker finishes with it. At startup the journal
is swept and every surviving entry is re-enqueued (see
:meth:`AnalysisSyncer.recover_journal`).

Re-running a recovered analysis is an idempotent upsert rather than a duplicate,
which is what makes the sweep safe to arm by default: an analysis uuid is the
deterministic hash of its identity and inputs
(:meth:`~helao.core.drivers.data.analyses.base_analysis.BaseAnalysis.gen_uuid`),
so the second run lands on the same uuid, the same local ANALYSES path and the
same S3 keys as the first. This is the opposite of a run uuid (``uuid7``, 48
random bits), where re-running is what the batch converter's recovery goes to
such lengths to avoid.
"""

__all__ = [
    "ANA_JOURNAL_SCHEMA",
    "ANA_JOURNAL_SUBDIR",
    "ANA_JOURNAL_FAILED_SUBDIR",
    "ANA_JOURNAL_SUFFIX",
    "AnalysisSyncer",
    "AnalysisExecutor",
    "AnalysisLoadError",
    "analysis_journal_key",
    "journal_entry_path",
    "list_journal_entries",
    "load_analysis_classes",
    "make_analysis_app",
    "read_journal_entry",
    "remove_journal_entry",
    "resolve_analyses_package",
    "write_journal_entry",
]

import asyncio
import hashlib
import inspect
import json
import os
import time
from importlib import import_module, util as importlib_util
from typing import TYPE_CHECKING, Optional
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
from helao.helpers import config_loader
from helao.helpers import helao_logging as logging
from helao.helpers.executor import Executor
from helao.hexagon.app.action_context import ActionContext
from helao.hexagon.app.action_host import ActionHost

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def _alert(message: str, exc_info: bool = False) -> None:
    """Raise an alert through the module logger, falling back to ``error``.

    ``helao_logging`` installs ``alert`` with ``setattr(logging.Logger, "alert",
    ...)`` at import (``helao_logging.py:70``), i.e. on the *class* -- so every
    ``logging.Logger`` in a process that has loaded this module does carry it,
    and the direct ``LOGGER.alert`` calls this replaces could not actually raise.
    What the class patch does not reach is a logger that is not a
    ``logging.Logger`` at all: a ``LoggerAdapter``, or a test's stub. Alerts here
    are the mechanism by which a lost analysis stops being invisible, so an alert
    must never itself be the thing that raises.

    ``LOGGER`` is read at call time rather than bound as a default, so a test
    that replaces the module logger is honoured. Also invisible to static
    analysis, which is why pyright reports ``alert`` as unknown on ``Logger``;
    resolving it through ``getattr`` keeps the type checker quiet as well.
    """
    emit = getattr(LOGGER, "alert", None) or LOGGER.error
    emit(message, exc_info=exc_info)


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


#: Subdirectory of ``<root>/STATES`` holding the pending-analysis journal.
ANA_JOURNAL_SUBDIR = "ana_pending"
#: Where a failed analysis's journal entry is moved to. Kept rather than
#: deleted so the failure is diagnosable and requeueable, moved rather than
#: left in place so the startup sweep does not re-run a poison item at every
#: restart -- the failure mode the syncer has on its own side.
ANA_JOURNAL_FAILED_SUBDIR = "ana_failed"

#: Extension of one journal entry. Anything else in the directory (notably the
#: ``.json.tmp`` an interrupted atomic write leaves behind) is not an entry.
ANA_JOURNAL_SUFFIX = ".json"

#: Schema version of a journal entry's payload. Bump when a field's meaning
#: changes; a sweep refuses an entry from a newer schema rather than guessing at
#: it, the way ``batch_converter``'s checkpoints do.
ANA_JOURNAL_SCHEMA = 1


def analysis_journal_key(target: str, process_uuid, analysis_class_name: str) -> str:
    """Return the journal file name for one analysis request.

    Derived from the three things that identify the request -- the loader
    ``target`` (the zip or run tree being analysed), the process uuid, and the
    analysis class -- so re-journalling the same request **overwrites** its entry
    instead of accumulating a second one. That matters on the recovery path,
    which re-enqueues an entry and thereby re-journals it.

    The uuid leads the name, unhyphenated separator ``__``, because
    :meth:`AnalysisSyncer.journal_clear_by_process` can only match on a process
    uuid (see its docstring) and does so by this prefix. ``target`` is folded
    into a short digest rather than spelled out: it is an absolute path, so it
    carries separators and is far too long for a file name.

    Args:
        target: ``LocalLoader.target`` -- the absolute zip/tree path.
        process_uuid: Process uuid the analysis runs on.
        analysis_class_name: ``__name__`` of the :class:`BaseAnalysis` subclass.

    Returns:
        ``<process uuid>__<class name>__<12-hex digest>.json``.
    """
    digest = hashlib.sha1(
        "\x1f".join([str(target), str(process_uuid), str(analysis_class_name)]).encode(
            "utf8", errors="replace"
        )
    ).hexdigest()[:12]
    return f"{process_uuid}__{analysis_class_name}__{digest}{ANA_JOURNAL_SUFFIX}"


def journal_entry_path(journal_dir: str, key: str) -> str:
    """Return the full path of journal entry ``key`` inside ``journal_dir``."""
    return os.path.join(journal_dir, key)


def list_journal_entries(journal_dir: Optional[str]) -> list:
    """Return the sorted journal entry file names in ``journal_dir``.

    Filters to :data:`ANA_JOURNAL_SUFFIX`, which excludes the ``.json.tmp``
    files an interrupted atomic write leaves behind -- sweeping one of those as
    an entry would parse a half-written payload. Returns ``[]`` for a missing or
    unreadable directory, and for journalling being disabled altogether
    (``journal_dir`` of ``None``).
    """
    if not journal_dir:
        return []
    try:
        return sorted(
            name
            for name in os.listdir(journal_dir)
            if name.endswith(ANA_JOURNAL_SUFFIX)
        )
    except FileNotFoundError:
        # Not yet created (nothing has ever been queued on this root), which is
        # not worth a warning -- it is the normal state of a fresh install.
        return []
    except OSError:
        LOGGER.warning(f"could not list analysis journal dir {journal_dir}")
        return []


def read_journal_entry(path: str) -> Optional[dict]:
    """Read one journal entry, or ``None`` when it carries no usable payload.

    ``None`` covers "absent", "unreadable" and "not an object" together so the
    sweep has exactly one no-information case. A corrupt entry is logged and
    skipped rather than raised: taking a whole recovery sweep down over one bad
    json file would strand every other queued analysis, which is precisely the
    silent loss this journal exists to end.
    """
    try:
        with open(path, "r", encoding="utf8") as handle:
            entry = json.load(handle)
    except FileNotFoundError:
        return None
    except Exception:
        LOGGER.warning(f"unreadable analysis journal entry {path}; skipping it")
        return None
    if not isinstance(entry, dict):
        LOGGER.warning(f"analysis journal entry {path} is not an object; skipping it")
        return None
    return entry


def write_journal_entry(journal_dir: str, key: str, entry: dict) -> bool:
    """Atomically write ``entry`` as journal file ``key``. Never raises.

    ``tmp`` + :func:`os.replace`, so a concurrent sweep never reads a
    half-written entry. Failure is logged and reported as ``False`` because
    bookkeeping must never be the thing that breaks the real work: an analysis
    whose journal write failed still runs, it merely stops being recoverable.

    Args:
        journal_dir: Directory to write into.
        key: File name from :func:`analysis_journal_key`.
        entry: Payload; ``schema`` and ``queued_at`` are filled in here.

    Returns:
        ``True`` on success, ``False`` if the write failed.
    """
    path = journal_entry_path(journal_dir, key)
    payload = dict(entry)
    payload["schema"] = ANA_JOURNAL_SCHEMA
    payload["queued_at"] = time.time()
    tmp = f"{path}.tmp"
    try:
        os.makedirs(journal_dir, exist_ok=True)
        with open(tmp, "w", encoding="utf8") as handle:
            json.dump(payload, handle, indent=2, default=str)
        os.replace(tmp, path)
        return True
    except Exception:
        LOGGER.error(f"could not write analysis journal entry {path}", exc_info=True)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False


def remove_journal_entry(path: str) -> None:
    """Delete one journal entry if it is there. Never raises."""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError:
        LOGGER.warning(f"could not remove analysis journal entry {path}")


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
        journal_dir: Directory holding the durable request journal, or ``None``
            when journalling is disabled (no resolvable ``STATES`` root).
        loader: S3/metadata loader shared with analysis classes via ``pgs3.LOADER``.
        s3: S3 client from the loader.
        s3r: S3 resource from the loader.
        bucket: S3 bucket name.
        region: S3 region.
    """

    base: "ActionHost"
    running_tasks: dict

    def __init__(self, action_serv: "ActionHost"):
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
        self.journal_dir = self._resolve_journal_dir(action_serv)

        self.syncer_loops = {
            i: asyncio.create_task(self.syncer(), name=f"syncer_loop__{i}")
            for i in range(self.max_tasks)
        }

    @staticmethod
    def _resolve_journal_dir(action_serv: "ActionHost") -> Optional[str]:
        """Return ``<STATES>/ana_pending``, or ``None`` to disable journalling.

        The ``STATES`` root is read off the action server's own
        :class:`~helao.core.models.helaodirs.HelaoDirs` (``ActionHost.helaodirs``,
        built by :func:`~helao.helpers.helao_dirs.helao_dirs` from the world
        config's ``root``) rather than re-resolved from the config here, so the
        journal cannot end up under a different root than the rest of the
        server's state.

        Every field of ``HelaoDirs`` is ``None`` when the config carries no
        ``root``, which is a supported construction (the host itself only warns),
        and a test double need not carry ``helaodirs`` at all. Either way the
        answer is ``None``: journalling degrades to off with one WARNING and the
        server keeps behaving exactly as it did before the journal existed.
        """
        states_root = getattr(
            getattr(action_serv, "helaodirs", None), "states_root", None
        )
        if not states_root:
            LOGGER.warning(
                "No STATES root is available, so queued analyses will not be "
                "journalled; a restart will silently drop whatever is queued."
            )
            return None
        path = os.path.join(str(states_root), ANA_JOURNAL_SUBDIR)
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            LOGGER.warning(
                f"Could not create the analysis journal dir {path}; queued "
                "analyses will not be journalled.",
                exc_info=True,
            )
            return None
        LOGGER.info(f"Analysis request journal at {path}.")
        return path

    def _journal_key(self, calc_tup: tuple) -> Optional[str]:
        """Return the journal file name for ``calc_tup``, or ``None`` if unknown.

        A pure function of the tuple, which is the whole point: the completion
        path can recompute the exact key from the tuple it just finished with,
        so no queued-item-to-journal-path mapping has to be maintained anywhere
        (and none can go stale). ``None`` when the loader carries no ``target``
        -- a stand-in loader in a test, or a loader kind that is not
        :class:`LocalLoader` -- since without a target there is nothing a
        recovered entry could be rebuilt from.
        """
        target = getattr(calc_tup[1], "target", None)
        if not target:
            return None
        ana_cls = calc_tup[3]
        return analysis_journal_key(
            str(target), calc_tup[0], getattr(ana_cls, "__name__", str(ana_cls))
        )

    def journal_write(self, calc_tup: tuple) -> Optional[str]:
        """Record ``calc_tup`` in the journal. Returns the path, or ``None``.

        Called by :meth:`enqueue_calc` **before** the item reaches the queue.
        The order is the mechanism: a crash in the gap between the two leaves a
        recoverable record on disk, whereas the reverse order leaves a queued
        analysis with nothing written about it -- exactly the loss this journal
        exists to end.

        The entry records the loader's ``target`` rather than the loader, which
        is what makes it serialisable at all: ``LocalLoader.__init__`` keeps the
        absolute path on ``self.target``, so ``LocalLoader(target)`` rebuilds an
        equivalent loader on the recovery path.

        Never raises. A journal that cannot be written is a lost *recovery*
        guarantee, not a lost analysis.
        """
        if not self.journal_dir:
            return None
        try:
            key = self._journal_key(calc_tup)
            if key is None:
                LOGGER.warning(
                    "Queued analysis has no loader target, so it cannot be "
                    "journalled; a restart would drop it."
                )
                return None
            process_uuid, data_loader, params, ana_cls, action_uuid = calc_tup
            entry = {
                "target": str(getattr(data_loader, "target", "")),
                "process_uuid": str(process_uuid),
                "params": params if isinstance(params, dict) else {},
                # The class NAME, resolved back to a class at recovery time
                # against the same ``analyses`` mapping make_analysis_app built
                # -- a class object is not serialisable, and an import path
                # would pin the entry to one deployment's module layout.
                "analysis_class": getattr(ana_cls, "__name__", str(ana_cls)),
                "analysis_module": getattr(ana_cls, "__module__", ""),
                "analysis_action_uuid": (
                    None if action_uuid is None else str(action_uuid)
                ),
            }
            if write_journal_entry(self.journal_dir, key, entry):
                return journal_entry_path(self.journal_dir, key)
        except Exception:
            LOGGER.error("Failed to journal a queued analysis.", exc_info=True)
        return None

    def journal_clear(self, calc_tup: tuple) -> None:
        """Drop ``calc_tup``'s journal entry, its worker having finished with it.

        Keyed by recomputing :meth:`_journal_key` from the tuple, so the entry
        removed is exactly the one :meth:`journal_write` created -- see
        :meth:`journal_clear_by_process` for why the task-name route cannot be
        that precise.

        Removed on **success only**. It used to be removed on completion of
        either kind, to stop a permanently-failing analysis re-running at every
        restart -- a real concern, and the failure mode the syncer has on its
        own side. But deleting the entry also destroyed the only durable record
        that the analysis had not run, so a failure became both unretryable and
        undiagnosable. :meth:`journal_quarantine` keeps the record and moves it
        aside instead, which answers the re-run concern without the erasure.

        The journal's job is to survive an *interruption* -- a crash, a kill, a
        graceful stop -- which is exactly the case where no worker reaches here.
        """
        if not self.journal_dir:
            return
        try:
            key = self._journal_key(calc_tup)
            if key is not None:
                remove_journal_entry(journal_entry_path(self.journal_dir, key))
        except Exception:
            LOGGER.warning("Failed to clear an analysis journal entry.", exc_info=True)

    def journal_quarantine(self, calc_tup: tuple) -> None:
        """Move ``calc_tup``'s journal entry aside after its analysis failed.

        Kept, because deleting it is what made a failed analysis invisible: the
        entry is the only place the loader target and analysis class survive, so
        erasing it left an ALERT line naming a process uuid and nothing to
        resolve it against. Moved, because leaving it in ``ana_pending`` means
        the next startup sweep re-runs it, and a genuinely un-analysable record
        then fails at every restart forever.

        Lands in ``<STATES>/ana_failed/`` under the same filename, so requeueing
        after a fix is a move back. Best effort: a quarantine that cannot be
        written must not take down the worker that was already failing.
        """
        if not self.journal_dir:
            return
        try:
            key = self._journal_key(calc_tup)
            if key is None:
                return
            src = journal_entry_path(self.journal_dir, key)
            if not os.path.exists(src):
                return
            failed_dir = os.path.join(
                os.path.dirname(self.journal_dir), ANA_JOURNAL_FAILED_SUBDIR
            )
            os.makedirs(failed_dir, exist_ok=True)
            os.replace(src, os.path.join(failed_dir, os.path.basename(src)))
            LOGGER.warning(
                f"Quarantined the journal entry for {calc_tup[0]} in {failed_dir}; "
                "it will not be re-run until it is moved back."
            )
        except Exception:
            LOGGER.warning(
                "Failed to quarantine an analysis journal entry.", exc_info=True
            )

    def journal_clear_by_process(self, process_uuid_str: str) -> None:
        """Drop every journal entry for one process uuid. Best effort.

        The seam for a caller that has only a task *name* -- which is the process
        uuid, and therefore not the journal key: the key also carries the loader
        target and the analysis class, so one process uuid can in principle own
        several entries. Matching by the name prefix removes all of them, which
        is a superset of what such a caller means. :meth:`syncer` uses the exact
        :meth:`journal_clear` instead and does not go through here.
        """
        if not self.journal_dir:
            return
        prefix = f"{process_uuid_str}__"
        for name in list_journal_entries(self.journal_dir):
            if name.startswith(prefix):
                remove_journal_entry(journal_entry_path(self.journal_dir, name))

    def journal_pending_keys(self) -> list:
        """Journal entry file names currently on disk, for the status endpoint."""
        return list_journal_entries(self.journal_dir)

    async def recover_journal(self, analysis_classes: dict) -> dict:
        """Re-enqueue every analysis the journal still holds. Startup sweep.

        An entry survives only when its worker never finished with it, so every
        one found here is an analysis that was requested, reported as
        successfully requested by its action, and then lost to a restart. The
        sweep is what stops that from being silent: anything recovered is raised
        as an alert, not merely logged.

        Re-running is an idempotent upsert rather than a duplicate, which is why
        this is armed by default and needs no delete-then-rerun dance:
        ``BaseAnalysis.gen_uuid`` hashes the analysis name, params, process uuid,
        sample label, codehash and run_use, so the recovered run mints the *same*
        analysis uuid and writes the same local path and S3 keys as the run it is
        repeating.

        Four dispositions, all of which keep the sweep going:

        * **re-enqueued** -- the zip is there and the analysis class is
          configured on this host.
        * **deleted** -- the loader ``target`` no longer exists. The entry can
          never run again, so leaving it would alert on every restart forever;
          it is removed and alerted once, naming the entry and the path.
        * **left in place, unconfigured** -- the entry names an analysis class
          this host does not serve. Another host in the group may own it (the
          ``analyses`` list is per server), so deleting it here would destroy
          another server's work. Logged, untouched.
        * **left in place, unreadable** -- corrupt json, a missing field, or a
          ``schema`` newer than this build's. Logged and skipped; a human decides.

        Args:
            analysis_classes: The endpoint-name-to-class mapping
                :func:`make_analysis_app` built from ``params.analyses``.

        Returns:
            ``{"pending", "recovered", "dropped", "unconfigured", "failed"}``.
        """
        summary = {
            "pending": 0,
            "recovered": 0,
            "dropped": 0,
            "unconfigured": 0,
            "failed": 0,
        }
        if not self.journal_dir:
            LOGGER.info("Analysis journal is disabled; no recovery sweep to run.")
            return summary

        by_name = {cls.__name__: cls for cls in (analysis_classes or {}).values()}
        names = list_journal_entries(self.journal_dir)
        summary["pending"] = len(names)
        if not names:
            LOGGER.info("Analysis journal is empty; nothing to recover.")
            return summary

        # One loader per distinct zip, matching the live path, where batch_calc
        # shares a single LocalLoader across every process of one sequence.
        # Building one is a full index of the archive, so this is not a
        # micro-optimisation on a plate with dozens of processes.
        loaders: dict = {}
        for name in names:
            path = journal_entry_path(self.journal_dir, name)
            entry = read_journal_entry(path)
            if entry is None:
                summary["failed"] += 1
                continue
            try:
                schema = int(entry.get("schema", ANA_JOURNAL_SCHEMA))
            except (TypeError, ValueError):
                schema = ANA_JOURNAL_SCHEMA
            if schema > ANA_JOURNAL_SCHEMA:
                LOGGER.warning(
                    f"Analysis journal entry {name} carries schema {schema}, newer "
                    f"than this build's {ANA_JOURNAL_SCHEMA}; leaving it alone "
                    "rather than guessing at its meaning."
                )
                summary["failed"] += 1
                continue

            target = str(entry.get("target") or "")
            class_name = str(entry.get("analysis_class") or "")
            if not target or not class_name or not entry.get("process_uuid"):
                LOGGER.warning(
                    f"Analysis journal entry {name} is missing target, "
                    "analysis_class or process_uuid; leaving it alone."
                )
                summary["failed"] += 1
                continue

            ana_cls = by_name.get(class_name)
            if ana_cls is None:
                LOGGER.info(
                    f"Analysis journal entry {name} names '{class_name}', which is "
                    "not in this server's params.analyses; leaving it for whichever "
                    "host serves that analysis."
                )
                summary["unconfigured"] += 1
                continue

            if not os.path.exists(target):
                _alert(
                    f"Analysis journal entry {name} cannot be recovered: its data "
                    f"path {target} no longer exists. The analysis requested for "
                    f"process {entry.get('process_uuid')} will never run; removing "
                    "the entry."
                )
                remove_journal_entry(path)
                summary["dropped"] += 1
                continue

            try:
                process_uuid = UUID(str(entry["process_uuid"]))
                action_uuid_raw = entry.get("analysis_action_uuid")
                action_uuid = (
                    None if not action_uuid_raw else UUID(str(action_uuid_raw))
                )
                params = entry.get("params")
                if not isinstance(params, dict):
                    params = {}
                if target not in loaders:
                    # Indexing a zip is blocking, so it does not belong on the
                    # server's event loop -- this sweep runs while the server is
                    # already answering requests.
                    loaders[target] = await asyncio.to_thread(LocalLoader, target)
            except Exception:
                _alert(
                    f"Could not rebuild the analysis in journal entry {name} from "
                    f"{target}; leaving the entry in place.",
                    exc_info=True,
                )
                summary["failed"] += 1
                continue

            await self.enqueue_calc(
                (process_uuid, loaders[target], params, ana_cls, action_uuid)
            )
            summary["recovered"] += 1

        message = (
            f"Analysis journal recovery: {summary['pending']} entr(ies) on disk, "
            f"{summary['recovered']} re-enqueued, {summary['dropped']} dropped as "
            f"unrunnable, {summary['unconfigured']} for another host, "
            f"{summary['failed']} unreadable."
        )
        if summary["recovered"]:
            # An alert, because the restart that lost these was itself silent:
            # each recovered analysis had already been reported as done by the
            # action that requested it.
            _alert(message)
        else:
            LOGGER.info(message)
        return summary

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

        **Not on this class's completion path, for two independent reasons.**
        Nothing in the tree calls it -- :meth:`syncer` does its own ``finally``
        cleanup instead, and clears the journal there by the exact key. And the
        identifier it keys on could not match anyway: ``task.get_name()`` returns
        the *asyncio task* name, which for the only tasks this class creates is
        ``syncer_loop__<i>`` (set in :meth:`__init__`), while ``running_tasks`` is
        keyed by **process uuid** -- ``syncer`` registers
        ``asyncio.current_task()``, the long-lived worker loop, under the uuid of
        whichever item it is handling. So the body below is inert here; it is the
        inherited :class:`HelaoSyncer` seam, where tasks *are* named per uuid.

        Kept, and taught to clear the journal, so that seam stays coherent if it
        is ever wired: by process uuid, which is all a task name can offer, and
        therefore a superset of one request (see
        :meth:`journal_clear_by_process`). The precise clear lives in
        :meth:`journal_clear`, which recomputes the key from the tuple itself.

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
            self.journal_clear_by_process(task_name)

    async def enqueue_calc(
        self,
        calc_tup: tuple[UUID, LocalLoader, dict, BaseAnalysis, Optional[UUID]],
    ):
        """Journal, then push, a single analysis tuple onto :attr:`task_queue`.

        The journal write comes first and deliberately so: the queue is in-memory
        and the requesting action returns as soon as this returns, so between the
        write and the ``put`` a crash loses nothing, while in the other order it
        loses the whole request. See :meth:`journal_write`.

        Args:
            calc_tup: ``(process_uuid, data_loader, ana_params, analysis_class,
                analysis_action_uuid)`` describing one analysis to run.
        """
        self.journal_write(calc_tup)
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
                # The journal entry stays: this item's analysis genuinely did not
                # run, so the next startup sweep should offer it again.
                self.task_queue.task_done()
                continue
            self.running_tasks[proc_uuid_str] = asyncio.current_task()
            cancelled = False
            failed = False
            try:
                await self.sync_ana(calc_tup)
            except asyncio.CancelledError:
                # A cancellation is an interruption, not an outcome: this is what
                # a graceful shutdown does to an analysis that is still running,
                # and its journal entry must survive so the next start re-enqueues
                # it. Without this flag the ``finally`` below would clear the
                # entry of the one analysis that certainly did NOT finish -- the
                # in-flight one -- while every queued sibling was preserved.
                # Re-raised so the worker loop still stops on cancellation.
                cancelled = True
                raise
            except Exception:
                # The loader target is in the message because the journal entry
                # that also recorded it is about to be kept-but-quarantined, and
                # because without it identifying WHICH sequence failed meant
                # searching a CIFS share by uuid. One field, hours saved.
                _alert(
                    f"Error in ana syncer worker for {proc_uuid_str} "
                    f"(target: {getattr(calc_tup[1], 'target', '?')})",
                    exc_info=True,
                )
                failed = True
            finally:
                self.running_tasks.pop(proc_uuid_str, None)
                self.task_set.discard(calc_tup[0])
                if not cancelled and not failed:
                    # Cleared on SUCCESS only. It used to clear on failure too,
                    # on the reasoning that the worker was done with the item --
                    # but that erased the only durable record of an analysis
                    # that did not run, so a failure was unretryable AND
                    # undiagnosable: 15 lost in one campaign, and the entry that
                    # would have named the sequence was deleted by the same
                    # line. A failure is not an outcome, it is an absence of
                    # one.
                    self.journal_clear(calc_tup)
                elif failed:
                    # Kept, but moved aside, so the next startup sweep does not
                    # re-run a poison item forever -- the failure mode the
                    # syncer has on its own side. Visible in the filesystem and
                    # requeued by hand once the cause is fixed.
                    self.journal_quarantine(calc_tup)
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
        """Report what a graceful stop is leaving behind for the next startup.

        Nothing is drained or awaited here: an analysis takes seconds to minutes
        and a shutdown hook is not the place to wait for one. The queue is
        discarded, as it always was -- what changed is that it is no longer
        discarded *silently*, because every queued item has a journal entry and
        :meth:`recover_journal` re-enqueues it on the next launch.
        """
        pending = self.journal_pending_keys()
        if pending:
            LOGGER.warning(
                f"Shutting down with {len(pending)} analysis request(s) still "
                f"journalled in {self.journal_dir}; they will be re-enqueued at "
                "the next startup."
            )
        elif self.task_set or self.running_tasks:
            LOGGER.warning(
                f"Shutting down with {len(self.task_set)} queued and "
                f"{len(self.running_tasks)} running analysis task(s) and no journal "
                "entries for them; these will be lost."
            )


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


def make_analysis_app(server_key) -> ActionHost:
    """Build the analysis FastAPI app with config-driven action endpoints.

    Constructs an :class:`ActionHost` backed by :class:`AnalysisSyncer` and registers
    one ``analyze_<module>`` action endpoint per analysis class named in the
    server config ``params.analyses`` list, plus the private ``list_running_tasks``
    and ``list_queued_tasks`` endpoints, and arms the startup sweep that
    re-enqueues whatever the request journal still holds.

    The analysis classes are resolved from the global ``CONFIG`` at app-build
    time (the driver instance is not created until the FastAPI ``startup``
    event, so it cannot be queried here). The server's ``legacy_module:`` and
    the loaded config's path go to :func:`resolve_analyses_package` alongside
    the world deployment, so a hexagon-grafted server still finds its own
    deployment's analyses.

    Args:
        server_key: Key identifying this server in the orchestration group.

    Returns:
        The configured :class:`ActionHost` application.

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

    app = ActionHost(
        server_key=server_key,
        server_title=server_key,
        description="Analysis server",
        version=1.0,
        driver_classes=[AnalysisSyncer],
    )

    def _register_endpoint(endpoint_name: str, ana_cls: BaseAnalysis):
        """Register one analysis action endpoint bound to ``ana_cls``."""

        # `path=` is required, not stylistic: @app.action() derives the path
        # from the handler's __name__, and this handler is named `_analyze` at
        # decoration time -- the rename to `endpoint_name` happens two lines
        # after the decorator has already run. Every config-declared analysis
        # would otherwise register at the same /<server>/_analyze.
        @app.action(path=f"/{server_key}/{endpoint_name}", name=endpoint_name)
        async def _analyze(
            ctx: ActionContext,
            sequence_zip_path: str = "",
            params: dict = {},
        ):
            f"""Action endpoint: run {ana_cls.__name__} on a sequence zip."""
            active = await ctx.begin()
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
    def list_queued_tasks() -> dict:
        """Return the queued analyses, in memory and on disk.

        The in-memory queue is under ``queued``, which is exactly what this
        endpoint used to return as its whole body. The shape widened to an object
        so the durable request journal is visible through the *existing* route
        rather than a new one: ``journal_pending``/``journal_keys`` are what a
        restart would re-enqueue, and their divergence from ``queued`` is how a
        journal write failure or a disabled journal shows up from outside the
        process. Nothing in the tree read the old body (checked: the only
        occurrences of ``list_queued_tasks`` anywhere are its own definition and
        priv's frozen route checklist, which pins the path and method, not the
        response schema).
        """
        return {
            "queued": [str(x) for x in app.driver.task_set],
            "running": list(app.driver.running_tasks.keys()),
            "journal_dir": app.driver.journal_dir,
            "journal_keys": app.driver.journal_pending_keys(),
            "journal_pending": len(app.driver.journal_pending_keys()),
        }

    # Hot-reload safety: defer restart while an analysis is queued or running.
    # ``app.driver`` is created in the host's own startup event, so wire the
    # hook from a startup handler (registered after the host's, hence run after
    # it). The hook still reads app.driver lazily.
    @app.on_event("startup")
    def _wire_hotreload_busy():
        app.hotreload_busy_hook = lambda: (
            app.driver is not None and app.driver.has_pending_work()
        )

    @app.on_event("startup")
    def _recover_journalled_analyses():
        """Re-enqueue whatever a previous process left in the request journal.

        Registered after the host's startup handler, so ``app.driver`` exists by
        the time this runs. It launches a task rather than awaiting the sweep:
        rebuilding a loader indexes a sequence zip, and holding up startup for
        that would delay the port bind and every route with it.

        Armed by default -- an unswept journal is the silent loss the journal
        exists to end -- and suppressible per server with
        ``params.analysis_recovery_on_startup: false``, matching the batch
        server's ``recovery_on_startup`` knob. Suppressing it stops only this
        pass; the entries stay on disk and stay visible through
        ``/list_queued_tasks``, so a backlog can be inspected before anything
        acts on it.
        """
        if app.driver is None:
            LOGGER.warning(
                "No analysis driver at startup; the request journal was not swept."
            )
            return
        if not app.driver.config_dict.get("analysis_recovery_on_startup", True):
            pending = len(app.driver.journal_pending_keys())
            LOGGER.warning(
                "analysis_recovery_on_startup is false, so the request journal was "
                f"not swept; {pending} entr(ies) are waiting in "
                f"{app.driver.journal_dir}."
            )
            return
        app.driver.recovery_task = asyncio.create_task(
            app.driver.recover_journal(analysis_classes),
            name="ana_journal_recovery",
        )

    return app
