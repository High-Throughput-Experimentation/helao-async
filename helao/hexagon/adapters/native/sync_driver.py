"""Native sync pipeline (hexagon P2c).

Verbatim re-body of the legacy sync driver
(``helao/core/drivers/data/sync_driver.py``): the module helpers,
``AsyncRWLock``, ``HelaoYml``, ``Progress``, and ``SyncDriver`` are
byte-identical copies of legacy lines 62-2057, source-parity-pinned per
member by ``test_native_sync_pins.py`` — including the 728a663c
process-recovery surface (``update_process`` unified metas,
``reconcile_processes`` cross-run replay, ``sync_process`` phantom-group
drop, estopped-children-terminal gate in ``sync_yml``). Class names are NOT
renamed: the copied bodies construct ``HelaoYml(...)`` / ``Progress(...)``
by name, so renaming would break byte-identity (D1).

The ONLY legacy import dropped is ``helao.core.servers.base.Base`` (D2):
the Base-coupled ``HelaoSyncer`` subclass is replaced by ``NativeSyncer``
(below the P2c native-only sentinel at the bottom of this module), which
replicates its config resolution against the narrow ``SyncerHost``
protocol — so this module imports only ``helao.helpers.*`` /
``helao.core.models.*`` and passes the adapters/native boundary rule.

Black-force-excluded (pyproject.toml): the legacy source is not black-clean
at 88. Only this docstring, the pyright file-scope suppression, ``__all__``,
two import-header lines (Base dropped, ``Protocol`` added to the typing
import), and the native-only section differ from legacy.
"""

# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportOptionalMemberAccess=false, reportOptionalSubscript=false

__all__ = ["AsyncRWLock", "HelaoYml", "Progress", "SyncDriver"]

import os
import shutil
import io
import codecs
import json
import asyncio
from configparser import ConfigParser
from zipfile import ZipFile
from pathlib import Path
from datetime import datetime
from typing import Union, Optional, Dict, List, Protocol
import traceback
from collections import defaultdict
from contextlib import AsyncExitStack, asynccontextmanager
from copy import copy

import boto3
import gzip

# from filelock import FileLock

from helao.helpers import helao_logging as logging

from helao.core.models.process import ProcessModel
from helao.core.models.action import ShortActionModel
from helao.helpers.premodels import Action
from helao.helpers.premodels import Experiment
from helao.helpers.premodels import Sequence
from helao.core.models.file import FileInfo
from helao.helpers.time_utils import gen_uuid
from helao.helpers.hlo_data import read_hlo
from helao.helpers.hlo_data import hlo_to_parquet
from helao.helpers.yml_tools import yml_dumps, yml_load
from helao.helpers.file_utils import zip_dir
from helao.core.models.helaodirs import HelaoDirs
from helao.helpers.dispatcher import async_action_dispatcher
from helao.core.models.machine import MachineModel
from helao.core.models.run_dir import RunDir, SYNC_PROGRESSION

from glob import glob

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
ABR_MAP = {"act": "action", "exp": "experiment", "seq": "sequence"}
MOD_MAP = {
    "action": Action,
    "experiment": Experiment,
    "sequence": Sequence,
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


def dict2json(input_dict: dict) -> io.BytesIO:
    """Serialize a dict to a UTF-8 JSON byte stream rewound to position 0.

    Args:
        input_dict: Dictionary to serialize.

    Returns:
        A ``BytesIO`` containing the JSON bytes, ready for upload.
    """
    bio = io.BytesIO()
    stream_writer = codecs.getwriter("utf-8")
    wrapper_file = stream_writer(bio)
    json.dump(input_dict, wrapper_file)
    bio.seek(0)
    return bio


def move_to_synced(file_path: Path) -> Union[Path, bool]:
    """Move a file from ``RUNS_FINISHED`` to the parallel ``RUNS_SYNCED`` path.

    No-op (returns the target path) when the file is already under
    ``RUNS_SYNCED`` or does not exist on disk.

    Args:
        file_path: Source file inside a ``RUNS_FINISHED`` tree.

    Returns:
        The new ``Path`` on success, or ``False`` on ``PermissionError``.
    """
    parts = list(file_path.parts)
    target_path = Path(
        str(file_path).replace(RunDir.FINISHED.value, RunDir.SYNCED.value)
    )
    if RunDir.SYNCED in parts:
        LOGGER.debug(f"File {file_path} is already synced. Skipping.")
        return target_path
    elif not file_path.exists():
        LOGGER.debug(f"File {file_path} does not exist. Skipping.")
        return target_path
    state_index = parts.index(RunDir.FINISHED)
    parts[state_index] = RunDir.SYNCED.value
    target_path = Path(*parts)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(file_path), str(target_path))
        return Path(target_path)
    except PermissionError:
        LOGGER.info(f"Permission error when moving {file_path} to {target_path}")
        return False


def revert_to_finished(file_path: Path) -> Union[Path, bool]:
    """Move a file from ``RUNS_SYNCED`` back to the parallel ``RUNS_FINISHED`` path.

    Args:
        file_path: Source file inside a ``RUNS_SYNCED`` tree.

    Returns:
        The new ``Path`` on success, or ``False`` on ``PermissionError``.

    Raises:
        ValueError: If ``RUNS_SYNCED`` is not present in the path.
    """
    parts = list(file_path.parts)
    state_index = parts.index(RunDir.SYNCED)
    parts[state_index] = RunDir.FINISHED.value
    target_path = Path(*parts)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        new_path = file_path.replace(target_path)
        return new_path
    except PermissionError:
        LOGGER.info(f"Permission error when moving {file_path} to {target_path}")
        return False


class AsyncRWLock:
    """A minimal asyncio reader/writer lock.

    Any number of readers may hold the lock concurrently, but a writer has it
    exclusively. This is reader-preferring: a waiting writer does not block new
    readers from entering. That matters for the syncer's sequence locks -- a
    sequence (writer) can only finish once its descendants (readers) have, so a
    writer must never stall the very readers it is waiting on.
    """

    def __init__(self):
        self._cond = asyncio.Condition()
        self._readers = 0
        self._writer = False

    @asynccontextmanager
    async def read_locked(self):
        """Acquire shared (reader) access for the duration of the context."""
        async with self._cond:
            while self._writer:
                await self._cond.wait()
            self._readers += 1
        try:
            yield
        finally:
            async with self._cond:
                self._readers -= 1
                if self._readers == 0:
                    self._cond.notify_all()

    @asynccontextmanager
    async def write_locked(self):
        """Acquire exclusive (writer) access for the duration of the context."""
        async with self._cond:
            while self._writer or self._readers > 0:
                await self._cond.wait()
            self._writer = True
        try:
            yield
        finally:
            async with self._cond:
                self._writer = False
                self._cond.notify_all()


class HelaoYml:
    """Wrapper around a single ``*-{seq,exp,act}.yml`` file inside a ``RUNS_*`` tree.

    Parses the YAML on construction, exposes the record's ``type``
    (sequence/experiment/action), ``timestamp``, and ``status``
    (active/finished/synced) derived from the file name and the parent
    ``RUNS_*`` directory, and provides helpers to find sibling/child ymls in
    the parallel active/finished/synced trees plus the associated hlo/misc/lock
    files.

    Attributes:
        target: Path to the YAML file.
        targetdir: Directory containing ``target``.
    """

    target: Path
    targetdir: Path

    def __init__(self, target: Union[Path, str]):
        """Locate the YAML file and load its metadata.

        Args:
            target: Path to a YAML file or its containing directory.
        """
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
    def parts(self) -> list:
        """Components of ``self.target`` as a list."""
        return list(self.target.parts)

    def check_paths(self):
        """Resolve ``self.target`` to an existing yml file and set ``targetdir``.

        If ``target`` doesn't exist, the active/finished/synced variants are
        probed in turn. If ``target`` is a directory, the single ``*-seq.yml``
        / ``*-exp.yml`` / ``*-act.yml`` inside is selected. The resolved
        directory must live under a ``RUNS_*`` parent.

        Raises:
            ValueError: If zero or more than one matching yml exists in a
                directory target, or the path is not under a ``RUNS_*`` tree.
        """
        if not self.exists:
            for p in (self.active_path, self.finished_path, self.synced_path):
                self.target = p
                if self.exists:
                    break
            if not self.exists:
                LOGGER.info(f"{self.target} does not exist")
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
    def exists(self) -> bool:
        """True if ``self.target`` exists on disk."""
        return self.target.exists()

    def __repr__(self) -> str:
        """Compact representation: ``<TYPE3>: <dirname> (<status>)``."""
        return f"{self.type[:3].upper()}: {self.target.parent.name} ({self.status})"

    @property
    def type(self) -> str:
        """Record type (``action``, ``experiment``, or ``sequence``)."""
        return ABR_MAP[self.target.stem.split("-")[-1]]

    @property
    def timestamp(self) -> datetime:
        """Timestamp parsed from the file name (``%y%m%d.%H%M%S%f`` or 4-digit year)."""
        try:
            ts = datetime.strptime(self.target.stem.split("-")[0], "%y%m%d.%H%M%S%f")
        except ValueError:
            ts = datetime.strptime(self.target.stem.split("-")[0], "%Y%m%d.%H%M%S%f")
        return ts

    @property
    def status(self) -> str:
        """Lowercase status (``active``/``finished``/``synced``) from the ``RUNS_*`` parent."""
        path_parts = [x for x in self.targetdir.parts if x.startswith("RUNS_")]
        status = path_parts[0].split("_")[-1].lower()
        return status

    @property
    def meta_status(self) -> list:
        """The ``<type>_status`` list from the yml meta (e.g. action_status).

        This is the in-file lifecycle status (a list of ``HloStatus`` values),
        distinct from :attr:`status` which is derived from the ``RUNS_*`` path.
        """
        return list(self.meta.get(f"{self.type}_status", []) or [])

    @property
    def is_estopped(self) -> bool:
        """True if this record's meta ``<type>_status`` contains ``estopped``.

        Matches both the enum value (``"estopped"``) and its ``repr``
        (``"HloStatus.estopped"``) so it is robust to how the status list was
        serialized into the yml.
        """
        return any("estopped" in str(s) for s in self.meta_status)

    def rename(self, status: str) -> str:
        """Return ``self.target`` with its ``RUNS_*`` segment replaced by ``status``.

        Args:
            status: New segment name (e.g. ``RUNS_SYNCED``).

        Returns:
            The rewritten path as a string.
        """
        tempparts = list(self.parts)
        tempparts[self.status_idx] = status
        return os.path.join(*tempparts)

    @property
    def status_idx(self) -> int:
        """Index in ``self.parts`` of the ``RUNS_{ACTIVE,FINISHED,SYNCED}`` segment.

        Raises:
            ValueError: If no valid status segment is present.
        """
        valid_statuses = SYNC_PROGRESSION
        return [any([x in valid_statuses]) for x in self.parts].index(True)

    @property
    def relative_path(self) -> str:
        """Path under the ``RUNS_*`` root, joined with forward slashes."""
        return "/".join(list(self.parts)[self.status_idx + 1 :])

    @property
    def active_path(self) -> Path:
        """``self.target`` rewritten under ``RUNS_ACTIVE``."""
        return Path(self.rename(RunDir.ACTIVE.value))

    @property
    def finished_path(self) -> Path:
        """``self.target`` rewritten under ``RUNS_FINISHED``."""
        return Path(self.rename(RunDir.FINISHED.value))

    @property
    def synced_path(self) -> Path:
        """``self.target`` rewritten under ``RUNS_SYNCED``."""
        return Path(self.rename(RunDir.SYNCED.value))

    def cleanup(self) -> str:
        """Remove empty parent directories under the ``RUNS_*`` root.

        Walks from the immediate parent upward through the ``RUNS_*`` segment
        and ``rmdir``\\ 's each level that is empty.

        Returns:
            ``"success"`` when all empty parents were removed (or there was
            nothing to do), ``"failed"`` when a directory was not empty, or a
            formatted traceback string when ``PermissionError`` was raised.
        """
        if not self.target.exists() or self.target == self.synced_path:
            return "success"
        tempparts = list(self.parts)
        steps = len(tempparts) - self.status_idx
        for i in range(1, steps):
            check_dir = Path(os.path.join(*tempparts[:-i]))
            contents = [x for x in check_dir.glob("*") if x != check_dir]
            if contents:
                LOGGER.info(f"{str(check_dir)} is not empty")
                LOGGER.info(contents)
                return "failed"
            try:
                check_dir.rmdir()
            except PermissionError as err:
                str_err = "".join(
                    traceback.format_exception(type(err), err, err.__traceback__)
                )
                return str_err
        return "success"

    def list_children(self, yml_path: Path) -> list:
        """Return ``HelaoYml`` siblings under ``yml_path.parent``, sorted by timestamp.

        Args:
            yml_path: Any yml file inside the parent directory to scan.

        Returns:
            ``HelaoYml`` objects for every ``*.yml`` one level below the
            parent, sorted oldest-first.
        """
        paths = yml_path.parent.glob("*/*.yml")
        hpaths = [HelaoYml(x) for x in paths]
        return sorted(hpaths, key=lambda x: x.timestamp)

    @property
    def active_children(self) -> list:
        """Children located under the ``RUNS_ACTIVE`` tree."""
        return self.list_children(self.active_path)

    @property
    def finished_children(self) -> list:
        """Children located under the ``RUNS_FINISHED`` tree."""
        return self.list_children(self.finished_path)

    @property
    def synced_children(self) -> list:
        """Children located under the ``RUNS_SYNCED`` tree."""
        return self.list_children(self.synced_path)

    @property
    def children(self) -> list:
        """Union of active/finished/synced children, sorted by timestamp."""
        all_children = (
            self.active_children + self.finished_children + self.synced_children
        )
        return sorted(all_children, key=lambda x: x.timestamp)

    @property
    def misc_files(self) -> List[Path]:
        """Files inside the target directory that are not ``.yml``/``.hlo``/``.lock``.

        Action ymls recurse into subdirectories; experiments and sequences
        only look at their immediate directory.
        """
        if self.type == "action":
            return [
                x
                for x in self.targetdir.rglob("*")
                if x.is_file()
                and not x.suffix == ".yml"
                and not x.suffix == ".hlo"
                and not x.suffix == ".lock"
            ]
        else:
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
        """``.lock`` files in the immediate target directory."""
        return [
            x for x in self.targetdir.glob("*") if x.is_file() and x.suffix == ".lock"
        ]

    @property
    def hlo_files(self) -> List[Path]:
        """``.hlo`` files in the immediate target directory."""
        return [
            x for x in self.targetdir.glob("*") if x.is_file() and x.suffix == ".hlo"
        ]

    @property
    def parent_path(self) -> Path:
        """Path of this record's parent yml.

        For sequences this is ``self.target`` (sequences have no parent); for
        actions/experiments it is the first yml found two directories up in
        any of the active/finished/synced trees.
        """
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
        """Serialize ``meta_dict`` to ``self.target`` as UTF-8 YAML.

        Args:
            meta_dict: Metadata to dump.
        """
        # with self.filelock:
        self.target.write_text(
            yml_dumps(meta_dict),
            encoding="utf-8",
        )


class Progress:
    """Sidecar ``.prg`` file tracking sync state for one ``HelaoYml``.

    The first time the progress file is opened it is initialized with default
    booleans (``api``/``s3`` = False) plus type-specific fields: actions get
    ``files_pending`` / ``files_s3`` lists, experiments get the per-process
    bookkeeping dicts (``process_metas``, ``process_groups``, etc.).
    Subsequent opens read the existing dict from disk.

    Attributes:
        ymlpath: Path of the parent yml.
        prg: Path of the ``.prg`` file (under ``RUNS_SYNCED``).
        dict: In-memory copy of the progress dict.
    """

    ymlpath: HelaoYml
    prg: Path
    dict: Dict

    def __init__(self, path: Union[Path, str]):
        """Resolve the yml/prg pair and load (or initialize) the progress dict.

        Args:
            path: Either the yml file under any ``RUNS_*`` tree or its
                companion ``.prg`` file under ``RUNS_SYNCED``.

        Raises:
            ValueError: If ``path`` is not a ``.yml`` or ``.prg`` file.
        """

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
            if not hasattr(self, "yml"):
                self.ymlpath = Path(self.dict["yml"])

    @property
    def yml(self) -> HelaoYml:
        """Freshly-constructed ``HelaoYml`` for ``self.ymlpath``."""
        return HelaoYml(self.ymlpath)

    def list_unfinished_procs(self) -> tuple:
        """Return ``(s3_unfinished, api_unfinished)`` process-group indices.

        For experiment ymls, returns the process group keys that have not yet
        landed in S3 / the API. For other yml types both lists are empty.
        """
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
        """Reload ``self.dict`` from the ``.prg`` file on disk."""
        self.dict = yml_load(self.prg)

    def write_dict(self, new_dict: Optional[Dict] = None):
        """Persist the progress dict to the ``.prg`` file as YAML.

        Args:
            new_dict: Override dict to write. Defaults to ``self.dict``.
        """
        out_dict = self.dict if new_dict is None else new_dict
        # with self.prglock:
        self.prg.write_text(str(yml_dumps(out_dict)), encoding="utf-8")

    @property
    def s3_done(self) -> bool:
        """Whether the yml has been pushed to S3."""
        return self.dict["s3"]

    @property
    def api_done(self) -> bool:
        """Whether the yml has been registered with the API."""
        return self.dict["api"]

    def remove_prg(self):
        """Delete the ``.prg`` file from disk."""
        # with self.prglock:
        self.prg.unlink()


class SyncDriver:
    """Async worker pool that pushes ``RUNS_FINISHED`` ymls to S3 and the API.

    Reads AWS credentials from ``AWS_CONFIG_PATH`` (or from the supplied
    config dict), spawns ``max_tasks`` ``syncer`` coroutines that pop entries
    off a shared queue, and serializes work on a per-experiment lock so
    actions belonging to the same experiment don't race their parent's
    progress dict.

    Attributes:
        progress: In-memory progress objects keyed by yml name.
        running_tasks: Asyncio tasks currently syncing, keyed by yml name.
    """

    progress: Dict[str, Progress]
    running_tasks: dict

    def __init__(self, config: dict, helaodirs: HelaoDirs):
        """Configure AWS access, queues, locks, and spawn the syncer workers.

        Args:
            config: Driver/server config dict; supplies AWS keys, bucket,
                ``api_host``, ``max_tasks``, and ``auto_analyze_sequences``.
            helaodirs: Resolved HELAO directory paths for this server.
        """
        self.config_dict = config
        self.helaodirs = helaodirs
        self.auto_analyses = self.config_dict.get("auto_analyze_sequences", {})
        cparser = ConfigParser()
        if "AWS_CONFIG_PATH" in os.environ:
            with open(os.environ["AWS_CONFIG_PATH"]) as f:
                cparser.read_file(f)
            aws_profile = self.config_dict.get("aws_profile", "default")
            if aws_profile in cparser:
                aws_config = dict(cparser[aws_profile])
                self.config_dict.update(aws_config)
                self.config_dict["aws_config_path"] = os.environ["AWS_CONFIG_PATH"]
                self.config_dict["aws_profile"] = aws_profile
                LOGGER.debug(self.config_dict)

        self.max_tasks = self.config_dict.get("max_tasks", 1)
        LOGGER.info("checking for aws_config_path")
        if "aws_config_path" in self.config_dict:
            os.environ["AWS_CONFIG_PATH"] = self.config_dict["aws_config_path"]
            self.aws_session = boto3.Session(
                aws_access_key_id=self.config_dict["aws_access_key_id"],
                aws_secret_access_key=self.config_dict["aws_secret_access_key"],
                region_name=self.config_dict["region"],
            )
            self.s3 = self.aws_session.client("s3")
            self.s3r = boto3.resource("s3")
        else:
            self.aws_session = None
            self.s3 = None
            self.s3r = None
        self.bucket = self.config_dict["aws_bucket"]
        self.api_host = self.config_dict.get("api_host", None)

        # self.progress = {}
        self.sequence_objs = {}
        self.task_queue = asyncio.PriorityQueue()
        self.task_set = set()
        self.running_tasks = {}
        # Hierarchical sync locks, keyed by each yml's path relative to RUNS_*
        # (so the key is stable as the yml moves between RUNS_FINISHED/SYNCED):
        #   - exp_locks: an exclusive per-experiment mutex held by the
        #     experiment sync AND every one of its child actions, so they never
        #     race the shared experiment progress dict / process metas.
        #   - seq_locks: a per-sequence reader/writer lock. Experiments and
        #     actions hold it as readers, so siblings still sync in parallel;
        #     the sequence sync holds it as the writer, which waits for every
        #     in-flight descendant and blocks until it owns the subtree --
        #     guaranteeing a parent never syncs concurrently with a descendant.
        self.exp_locks: Dict[str, asyncio.Lock] = {}
        self.seq_locks: Dict[str, AsyncRWLock] = {}
        self.aiolock = asyncio.Lock()
        # push happens via async task queue
        # processes are checked after each action push
        # pushing an exp before processes/actions have synced will first enqueue actions
        # then enqueue processes, then enqueue the exp again
        # exp progress must be in memory before actions are checked
        LOGGER.info("creating syncer tasks")
        self.syncer_loops = {
            i: asyncio.create_task(self.syncer(), name=f"syncer_loop__{i}")
            for i in range(self.max_tasks)
        }

    def try_remove_empty(self, remove_target) -> bool:
        """Recursively ``rmdir`` ``remove_target`` if it (and its subtree) are empty.

        Args:
            remove_target: Directory path to attempt to prune.

        Returns:
            True if ``remove_target`` (and any empty descendants) were
            removed, False otherwise.
        """
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
                LOGGER.error(
                    f"Directory {remove_target} is empty, but could not removed. {repr(err), tb,}"
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

    def cleanup_root(self, root_path: str):
        """Prune empty week/date directories under ``RUNS_ACTIVE`` and ``RUNS_FINISHED``.

        Walks the ``<root>/<RUNS_*>/<week>/<date>`` directory layout, attempts
        to remove date directories whose stamp is on or before today and are
        empty, and removes the parent week directory when that also becomes
        empty.

        Args:
            root_path: Base path containing the ``RUNS_*`` trees.
        """
        today = datetime.strptime(datetime.now().strftime("%y%m%d"), "%y%m%d")
        chkdirs = [RunDir.ACTIVE.value, RunDir.FINISHED.value]
        for cd in chkdirs:
            seq_dates = glob(os.path.join(root_path, cd, "*", "*"))
            for datedir in seq_dates:
                if not os.path.isdir(datedir):
                    continue
                try:
                    dateonly = datetime.strptime(os.path.basename(datedir), "%m%d")
                    dateonly.replace(
                        year=datetime.strptime(
                            os.path.basename(os.path.dirname(datedir)), "%y.%U"
                        ).year
                    )
                except ValueError:
                    dateonly = datetime.strptime(os.path.basename(datedir), "%Y%m%d")
                if dateonly <= today:
                    seq_dirs = glob(os.path.join(datedir, "*"))
                    if len(seq_dirs) == 0:
                        self.try_remove_empty(datedir)
                    weekdir = os.path.dirname(datedir)
                    if len(glob(os.path.join(weekdir, "*"))) == 0:
                        self.try_remove_empty(weekdir)

    def sync_exit_callback(self, task: asyncio.Task):
        """Drop the finished task from ``running_tasks`` and ``task_set``.

        Args:
            task: The asyncio task that just completed.
        """
        task_name = task.get_name()
        if task_name in self.running_tasks:
            LOGGER.debug(f"Removing {task_name} from running_tasks.")
            self.running_tasks.pop(task_name)
        try:
            LOGGER.debug(f"Removing {task_name} from task_set.")
            self.task_set.discard(task_name)
        except KeyError:
            pass

    @staticmethod
    def _rel_under_runs(path: Path) -> Optional[str]:
        """Return ``path`` relative to its ``RUNS_*`` root, or ``None`` if absent.

        Keying locks by a yml's position under the ``RUNS_*`` root keeps the
        key stable across the ``RUNS_{ACTIVE,FINISHED,SYNCED}`` trees, so the
        same logical record always maps to the same lock as it is moved.
        """
        parts = list(path.parts)
        run_idxs = [i for i, x in enumerate(parts) if x.startswith("RUNS_")]
        if not run_idxs:
            return None
        return "/".join(parts[run_idxs[0] + 1 :])

    def _node_keys(self, yml_path: Path) -> tuple:
        """Return ``(seq_key, exp_key)`` lock keys for ``yml_path``.

        Keys are the sequence and experiment *directory* paths relative to the
        ``RUNS_*`` root. ``exp_key`` is ``None`` for sequences (which have no
        experiment level). Returns ``(None, None)`` when the path is not under
        a ``RUNS_*`` tree.

        The layout is ``<runs>/<week>/<date>/<seq>/<exp>/<act>/<name>-*.yml``,
        so the directory levels are counted back from the file name and are
        independent of the week/date naming above the sequence.
        """
        rel = self._rel_under_runs(yml_path)
        if rel is None:
            return None, None
        parts = rel.split("/")
        stem = yml_path.stem
        if stem.endswith("-seq"):
            return "/".join(parts[:-1]), None
        if stem.endswith("-exp"):
            return "/".join(parts[:-2]), "/".join(parts[:-1])
        if stem.endswith("-act"):
            return "/".join(parts[:-3]), "/".join(parts[:-2])
        return None, None

    def _get_seq_lock(self, seq_key: str) -> AsyncRWLock:
        """Get-or-create the per-sequence reader/writer lock for ``seq_key``."""
        lock = self.seq_locks.get(seq_key)
        if lock is None:
            lock = AsyncRWLock()
            self.seq_locks[seq_key] = lock
        return lock

    def _get_exp_lock(self, exp_key: str) -> asyncio.Lock:
        """Get-or-create the exclusive per-experiment mutex for ``exp_key``."""
        lock = self.exp_locks.get(exp_key)
        if lock is None:
            lock = asyncio.Lock()
            self.exp_locks[exp_key] = lock
        return lock

    async def _acquire_hierarchy_locks(self, stack: AsyncExitStack, yml_path: Path):
        """Enter the hierarchical sync locks for ``yml_path`` into ``stack``.

        Locks are always taken outermost-first (sequence before experiment),
        giving a single global acquisition order that rules out deadlock:

        - a **sequence** takes its sequence lock as a *writer*, so it waits for
          every running descendant and excludes new ones;
        - an **experiment** takes its sequence lock as a *reader* (siblings run
          in parallel) plus its own experiment mutex;
        - an **action** takes its sequence lock as a *reader* plus its parent
          experiment's mutex, so it serializes with that experiment's sync and
          its sibling actions while staying concurrent with other experiments.

        Anything not under a ``RUNS_*`` tree (or an unrecognized type) is left
        unlocked.
        """
        seq_key, exp_key = self._node_keys(yml_path)
        if seq_key is None:
            return
        seq_lock = self._get_seq_lock(seq_key)
        if exp_key is None:  # sequence yml
            await stack.enter_async_context(seq_lock.write_locked())
            return
        await stack.enter_async_context(seq_lock.read_locked())
        await stack.enter_async_context(self._get_exp_lock(exp_key))

    async def syncer(self):
        """Worker coroutine: pop one yml off the queue and run :meth:`sync_yml`.

        ``self.max_tasks`` copies of this coroutine run concurrently. The
        hierarchical sync locks (see :meth:`_acquire_hierarchy_locks`) serialize
        a record against its ancestors and descendants while still letting
        unrelated subtrees sync in parallel.
        """
        while True:
            rank, yml_path = await self.task_queue.get()
            LOGGER.debug(f"Acquired {yml_path.name} with priority {rank}.")
            self.task_set.discard(yml_path.name)
            if yml_path.name in self.running_tasks:
                LOGGER.debug(f"{yml_path.name} sync is already in progress, skipping.")
                continue
            self.running_tasks[yml_path.name] = asyncio.current_task()
            try:
                async with AsyncExitStack() as locks:
                    await self._acquire_hierarchy_locks(locks, yml_path)
                    await self.sync_yml(yml_path=yml_path, rank=rank)
            except Exception:
                LOGGER.error(f"Error in syncer worker for {yml_path}", exc_info=True)
            finally:
                self.running_tasks.pop(yml_path.name, None)

    def get_progress(self, yml_path: Path) -> Progress:
        """Construct a ``Progress`` for ``yml_path``, creating the ``.prg`` if needed.

        Args:
            yml_path: Path to the yml whose progress is requested.

        Returns:
            A ``Progress`` bound to the resolved yml.
        """
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
        self, upath: Union[Path, str], rank: int = 0, rank_limit: int = -5
    ):
        """Add ``upath`` to the sync queue if it is not already queued/running.

        Args:
            upath: yml path to enqueue.
            rank: Priority for the queue entry (lower runs sooner).
            rank_limit: Floor below which enqueue requests are dropped to
                prevent runaway re-queuing.
        """
        yml_path = Path(upath) if isinstance(upath, str) else upath
        if rank < rank_limit:
            LOGGER.debug(
                f"{str(yml_path)} re-queue rank is under {rank_limit}, skipping enqueue request."
            )
        elif yml_path.name in self.task_set:
            LOGGER.info(f"{str(yml_path)} is already queued, skipping enqueue request.")
        elif yml_path.name in self.running_tasks.keys():
            LOGGER.debug(
                f"{str(yml_path)} is already running, skipping enqueue request."
            )
        else:
            # async with self.aiolock:
            self.task_set.add(yml_path.name)
            await self.task_queue.put((rank, yml_path))
            LOGGER.info(f"Added {str(yml_path)} to syncer queue with priority {rank}.")

