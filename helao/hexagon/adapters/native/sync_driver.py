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

__all__ = ["AsyncRWLock", "HelaoYml", "Progress"]

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


