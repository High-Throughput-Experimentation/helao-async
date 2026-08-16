"""Ship completed HELAO run trees to S3 and an upstream API.

Walks ``RUNS_FINISHED`` YAML trees (sequences, experiments, actions, and the
processes they contribute to), pushes raw HLO/parquet/misc files plus the
patched YAML metadata to S3, optionally registers each record with the API,
moves the on-disk tree to ``RUNS_SYNCED``, and finally zips the synced
sequence directory.

Public surface:
    HelaoYml: Wraps a single ``*-{seq,exp,act}.yml`` file and its directory,
        with helpers to locate active/finished/synced siblings.
    Progress: Tracks per-yml sync state in a sidecar ``.prg`` file.
    SyncDriver / HelaoSyncer: Worker that consumes a queue of yml paths,
        uploads to S3 / API, and rewrites the on-disk state.
    dict2json / move_to_synced / revert_to_finished: Module-level helpers.
"""

__all__ = ["HelaoYml", "Progress", "HelaoSyncer"]

import asyncio
import codecs
import gzip
import io
import json
import os
import shutil
import traceback
from collections import defaultdict
from configparser import ConfigParser
from contextlib import AsyncExitStack, asynccontextmanager
from copy import copy
from datetime import datetime
from glob import glob
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Optional, Union
from zipfile import ZipFile

import boto3

from helao.core.models.action import ShortActionModel
from helao.core.models.file import FileInfo
from helao.core.models.helaodirs import HelaoDirs
from helao.core.models.machine import MachineModel
from helao.core.models.process import ProcessModel
from helao.core.models.run_dir import SYNC_PROGRESSION, RunDir

if TYPE_CHECKING:  # pragma: no cover - typing only
    # B5: the host that constructs this driver. Annotation-only, so it costs
    # no import at runtime and does not bind helao/core/drivers to the app
    # layer -- but the NAME has to be right, because B7 deletes ``Base``.
    from helao.hexagon.app.action_host import ActionHost

# from filelock import FileLock
from helao.helpers import helao_logging as logging
from helao.helpers.dispatcher import async_action_dispatcher
from helao.helpers.file_utils import zip_dir
from helao.helpers.hlo_data import hlo_to_parquet, read_hlo
from helao.helpers.premodels import Action, Experiment, Sequence
from helao.helpers.server_keys import resolve_sync_server_key
from helao.helpers.time_utils import gen_uuid
from helao.helpers.yml_tools import yml_dumps, yml_load

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
        # fast=True: run ymls are read as data and re-emitted from the pydantic
        # models, never from the loaded object, so nothing here needs the
        # round-trip containers -- and those containers are what made syncing a
        # yml holding a long list quadratic (their __deepcopy__ is O(n^2), and
        # HelaoDict.as_dict used to copy them).
        self.meta = yml_load(self.target, fast=True)

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
    def misc_files(self) -> list[Path]:
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
    def lock_files(self) -> list[Path]:
        """``.lock`` files in the immediate target directory."""
        return [
            x for x in self.targetdir.glob("*") if x.is_file() and x.suffix == ".lock"
        ]

    @property
    def hlo_files(self) -> list[Path]:
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

    # Path, not HelaoYml: ``__init__`` only ever assigns a Path here, and the
    # ``yml`` property is what turns it into a HelaoYml. Declared as HelaoYml
    # the attribute typed as its own ``exists`` property -- a bool -- so any
    # ``self.ymlpath.exists()`` read as calling a bool.
    ymlpath: Path
    prg: Path
    dict: dict
    #: Last ``HelaoYml`` handed out by :attr:`yml`, and the ``(mtime_ns, size)``
    #: of the file it parsed. Reused only while that stamp still holds.
    _yml_cache: Optional[HelaoYml] = None
    _yml_cache_stamp: tuple = ()

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
            self.reanchor_recorded_paths()

    @staticmethod
    def _tail_after(parts: tuple, anchor: str):
        """Components of *parts* following the LAST occurrence of *anchor*.

        ``None`` when the anchor does not appear. Last rather than first
        because a record directory's name could in principle also name a
        subdirectory inside it; the deeper match is the correct one.
        """
        for i in range(len(parts) - 1, -1, -1):
            if parts[i] == anchor:
                return parts[i + 1 :]
        return None

    def relpath(self, path: Union[Path, str]) -> str:
        """*path* relative to this record's own directory, POSIX-style.

        **Recorded paths are relative because an absolute one is only true for
        the root it was written under.** Relocating the run trees -- inserting
        one ``DATA/`` level, say -- left every absolute entry in every sidecar
        naming a location that no longer existed, while the file itself sat
        untouched under the new root. ``sync_yml`` then raised ValueError from
        ``relative_to(targetdir)`` on a path it had recorded itself, the
        exception escaped to the worker, and the record returned to
        ``RUNS_FINISHED`` to fail identically at every restart.

        Falls back to the path unchanged when it cannot be placed inside this
        record at all. That is deliberate: a wrong guess would point the
        uploader at some other action's data, and a path left alone fails
        loudly at the next ``stat`` instead.
        """
        p = Path(str(path).replace("\\", "/"))
        base = self.yml.targetdir
        try:
            return p.relative_to(base).as_posix()
        except ValueError:
            pass
        if not p.is_absolute():
            return p.as_posix()
        tail = self._tail_after(p.parts, base.name)
        if not tail:
            return p.as_posix()
        return PurePosixPath(*tail).as_posix()

    def abspath(self, recorded: Union[Path, str]) -> Path:
        """Where a recorded path lives on disk, under the CURRENT root.

        An absolute entry is passed through rather than re-anchored: by the
        time anything calls this, :meth:`reanchor_recorded_paths` has already
        had its chance, so an absolute survivor is one that could not be placed
        and must not be silently redirected somewhere plausible.
        """
        p = Path(recorded)
        return p if p.is_absolute() else self.yml.targetdir / p

    def reanchor_recorded_paths(self) -> bool:
        """Convert absolute entries loaded from disk to record-relative ones.

        The migration half of the same fix, run on every read so a sidecar
        written before this change -- or before any future root move -- heals
        the first time it is opened. Nothing is written back here; the next
        :meth:`write_dict` persists the normalized form, so a record that is
        never touched again is never rewritten.

        Wrapped defensively: this runs inside ``__init__`` for every sidecar
        the syncer opens, and a record whose yml cannot currently be resolved
        must still load. Failing to normalize leaves the dict exactly as it was
        on disk, which is the pre-existing behaviour.

        Returns:
            ``True`` when anything changed.
        """
        try:
            changed = False
            pending = self.dict.get("files_pending")
            if isinstance(pending, list):
                fixed = [self.relpath(x) for x in pending]
                if fixed != pending:
                    self.dict["files_pending"] = fixed
                    changed = True
            uploaded = self.dict.get("files_s3")
            if isinstance(uploaded, dict):
                fixed_s3 = {self.relpath(k): v for k, v in uploaded.items()}
                if fixed_s3 != uploaded:
                    self.dict["files_s3"] = fixed_s3
                    changed = True
            # ``yml`` is absolute by design -- it is how a Progress built from a
            # .prg finds its record -- but it is just as root-bound, so restate
            # it from the yml this Progress actually resolved.
            if hasattr(self, "ymlpath"):
                current = str(self.yml.target)
                if self.dict.get("yml") != current:
                    self.dict["yml"] = current
                    changed = True
            return changed
        except Exception:  # pragma: no cover - defensive, see docstring
            LOGGER.warning(
                f"Could not re-anchor recorded paths in {getattr(self, 'prg', '?')}",
                exc_info=True,
            )
            return False

    @property
    def yml(self) -> HelaoYml:
        """``HelaoYml`` for ``self.ymlpath``, reused while the file is untouched.

        Constructing a ``HelaoYml`` re-parses the yml from disk, and
        ``sync_yml`` reads this property upwards of thirty times in a single
        pass -- so an unconditionally fresh object made the parse cost of one
        sync scale with the number of attribute reads, and dominated a sync
        even for a yml carrying no bulk data at all.

        The cached object is handed back only when re-constructing one would
        demonstrably reproduce it: the resolved target must still exist,
        unchanged in mtime and size, and must still be the file
        ``HelaoYml.check_paths`` would land on. Anything else -- the yml moved
        between RUNS_* trees, or was rewritten underneath us -- falls through
        to a fresh parse, which is exactly what the uncached property did.
        """
        cached = getattr(self, "_yml_cache", None)
        if cached is not None and (
            cached.target == self.ymlpath or not self.ymlpath.exists()
        ):
            try:
                stat = cached.target.stat()
            except OSError:
                stat = None
            if stat is not None and (
                stat.st_mtime_ns,
                stat.st_size,
            ) == self._yml_cache_stamp:
                return cached
        fresh = HelaoYml(self.ymlpath)
        try:
            stat = fresh.target.stat()
            self._yml_cache_stamp = (stat.st_mtime_ns, stat.st_size)
            self._yml_cache = fresh
        except OSError:
            # Nothing on disk to validate a cache entry against; never cache.
            self._yml_cache = None
        return fresh

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
        self.dict = yml_load(self.prg, fast=True)

    def write_dict(self, new_dict: Optional[dict] = None):
        """Persist the progress dict to the ``.prg`` file as YAML, atomically.

        Written to a sibling ``.tmp`` and moved into place with
        :func:`os.replace`, rather than truncating the live file. A plain
        ``write_text`` leaves a window in which the ``.prg`` on disk is empty or
        half-written, and this file is on a CIFS share where that window is not
        small. Any reader landing in it gets either a parse error or -- worse --
        a *partial* dict, which is one way an experiment ends up with
        ``process_actions_done`` recording actions whose ``process_metas``
        entries are absent: a divergence that cannot be rebuilt once the
        contributing action ymls have moved on, and that used to leave the
        experiment in a permanent re-enqueue loop (see
        :meth:`SyncDriver.sync_process`).

        The in-process hierarchical locks already serialize *writers* for one
        experiment (an action holds its parent's mutex, see
        :meth:`SyncDriver._acquire_hierarchy_locks`), so this is not about two
        syncer tasks racing. It closes the reader-side window, and the
        cross-process one that no asyncio lock can cover.

        Args:
            new_dict: Override dict to write. Defaults to ``self.dict``.
        """
        out_dict = self.dict if new_dict is None else new_dict
        tmp = self.prg.with_suffix(self.prg.suffix + ".tmp")
        tmp.write_text(str(yml_dumps(out_dict)), encoding="utf-8")
        os.replace(tmp, self.prg)

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

    progress: dict[str, Progress]
    running_tasks: dict

    def __init__(self, config: dict, helaodirs: HelaoDirs):
        """Configure AWS access, queues, locks, and spawn the syncer workers.

        Args:
            config: Driver/server config dict; supplies AWS keys, bucket,
                ``max_tasks``, and ``auto_analyze_sequences``.
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
        self.exp_locks: dict[str, asyncio.Lock] = {}
        self.seq_locks: dict[str, AsyncRWLock] = {}
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

    def has_pending_work(self) -> bool:
        """True while any yml is queued for or actively being synced.

        Consulted by the server's ``/hotreload_busy`` hook so the hot-reload
        watcher will not restart the syncer mid-flight -- action servers get no
        ``--restore``, so a restart would drop the in-memory ``task_queue``.
        """
        return self.task_queue.qsize() > 0 or bool(self.running_tasks)

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

    async def sync_yml(
        self,
        yml_path: Path,
        retries: int = 3,
        rank: int = 5,
        force_s3: bool = False,
        force_api: bool = False,
        compress: bool = False,
    ):
        """Run the full sync pipeline for a single yml file.

        Steps: verify the yml is finished and its children are synced, upload
        action HLO/misc files to S3 (or convert >1GB hlo to parquet first),
        finalize any pending processes for an experiment, push the patched
        metadata JSON to S3 and the API, and finally move the yml plus its
        files to ``RUNS_SYNCED`` (zipping the sequence directory on success).

        Args:
            yml_path: yml file to sync.
            retries: Number of times to retry pending process sync. Defaults to 3.
            rank: Current queue priority for re-enqueue logic.
            force_s3: Re-push to S3 even if previously done.
            force_api: Re-push to API even if previously done.
            compress: Gzip JSON bodies before uploading to S3.

        Returns:
            On success, the progress dict (minus ``process_metas``) as the
            shipped state; ``True`` if there was nothing to sync; ``False``
            when the yml could not be synced this pass.
        """
        if not yml_path.exists():
            LOGGER.debug(
                f"{str(yml_path)} does not exist, assume yml has moved to synced."
            )
            return True
        # if yml_path.name in self.task_set:
        #     async with self.aiolock:
        #         self.task_set.remove(yml_path.name)
        prog = self.get_progress(yml_path)
        if not prog:
            LOGGER.debug(
                f"{str(yml_path)} does not exist, assume yml has moved to synced."
            )
            return True

        meta = copy(prog.yml.meta)

        if prog.yml.status == "synced":
            LOGGER.debug(
                f"Cannot sync {str(prog.yml.target)}, status is already 'synced'."
            )
            return True

        LOGGER.debug(
            f"{str(prog.yml.target)} status is not synced, checking for finished."
        )

        if prog.yml.status == "active":
            LOGGER.debug(
                f"Cannot sync {str(prog.yml.target)}, status is not 'finished'."
            )
            return False

        LOGGER.debug(f"{str(prog.yml.target)} status is finished, proceeding.")

        # first check if child objects are registered with API (non-actions).
        # Concurrency with descendants is prevented by the hierarchical sync
        # locks acquired in the syncer worker, so this method only needs to
        # gate on child *sync status*, not on whether children are running.
        if prog.yml.type != "action":
            active_children = prog.yml.active_children
            # An estopped child left stranded in RUNS_ACTIVE is terminal: it will
            # never finish or move on its own, so it must not block the parent
            # forever. Only genuinely-still-running (non-estopped) active children
            # gate the parent. The estopped ones' process contributions are still
            # picked up by reconcile_processes (which reads active children too).
            blocking_active = [c for c in active_children if not c.is_estopped]
            if blocking_active:
                LOGGER.debug(
                    f"Cannot sync {str(prog.yml.target)}, children are still 'active'."
                )
                return False
            if active_children:
                LOGGER.warning(
                    f"{str(prog.yml.target)} has {len(active_children)} estopped "
                    f"child(ren) stranded in RUNS_ACTIVE; treating as terminal and "
                    f"proceeding with sync."
                )
            if prog.yml.finished_children:
                LOGGER.debug(
                    f"Cannot sync {str(prog.yml.target)}, children are not 'synced'."
                )
                # Re-queue this parent *below* its children, and decrement the
                # rank on every pass so the rank_limit floor in enqueue_yml
                # eventually bounds the retries. Re-queuing at a higher rank
                # (rank + 1) never approaches the floor, so a child that keeps
                # failing (or can't be synced) would re-queue the parent
                # forever -- the infinite loop this method must avoid.
                parent_rank = rank - 1
                child_rank = parent_rank - 1
                LOGGER.debug(
                    f"Adding 'finished' children to sync queue at rank {child_rank} "
                    f"(higher priority than parent rank {parent_rank})."
                )
                # Re-submit every unsynced child. enqueue_yml is the single
                # dedup point: a child still queued/running is skipped, while a
                # child whose sync failed (and so left task_set/running_tasks)
                # is re-queued at strictly higher priority than this parent.
                for child in prog.yml.finished_children:
                    await self.enqueue_yml(child.target, child_rank)
                    LOGGER.info(str(child.target))
                LOGGER.debug(
                    f"Re-adding {str(prog.yml.target)} to sync queue at rank {parent_rank}."
                )
                if prog.yml.target.name in self.running_tasks:
                    async with self.aiolock:
                        self.running_tasks.pop(prog.yml.target.name)
                self.task_set.discard(prog.yml.target.name)
                await self.enqueue_yml(prog.yml.target, parent_rank)
                LOGGER.debug(f"{str(prog.yml.target)} re-queued, exiting.")
                return False

        LOGGER.debug(f"{str(prog.yml.target)} children are synced, proceeding.")

        # next push files to S3 (actions only)
        if prog.yml.type == "action":
            # re-check file lists
            LOGGER.debug(f"Checking file lists for {prog.yml.target.name}")
            # Recorded RELATIVE to the record directory: an absolute entry is
            # only true for the root it was written under, and a later
            # relocation of the run trees strands every one of them.
            prog.dict["files_pending"] += [
                rel
                for rel in (
                    prog.relpath(p)
                    for p in prog.yml.hlo_files + prog.yml.misc_files
                )
                if rel not in prog.dict["files_pending"]
                and rel not in prog.dict["files_s3"]
            ]
            # push files to S3
            while prog.dict.get("files_pending", []):
                for sp in prog.dict["files_pending"]:
                    fp = prog.abspath(sp)
                    LOGGER.debug(f"Pushing {sp} to S3 for {prog.yml.target.name}")
                    if fp.suffix == ".hlo":
                        if fp.stat().st_size < 1024**3:  # 1GB
                            file_s3_key = (
                                f"raw_data/{meta['action_uuid']}/{fp.name}.json"
                            )
                            if compress:
                                file_s3_key += ".gz"
                            LOGGER.debug("Parsing hlo dicts.")
                            try:
                                file_meta, file_data = await asyncio.to_thread(
                                    read_hlo, sp
                                )
                            except Exception:
                                LOGGER.error(
                                    f"Failed to read hlo file {fp}, skipping upload.",
                                    exc_info=True,
                                )
                                file_meta = {}
                                file_data = {}
                            msg = {"meta": file_meta, "data": file_data}
                        else:
                            LOGGER.debug(
                                "hlo file larger than 1GB, converting to parquet."
                            )
                            file_s3_key = (
                                f"raw_data/{meta['action_uuid']}/{fp.stem}.parquet"
                            )
                            try:
                                parquet_path = str(fp).replace(".hlo", ".parquet")
                                await asyncio.to_thread(
                                    hlo_to_parquet, fp, parquet_path
                                )
                                msg = Path(parquet_path)
                            except Exception:
                                LOGGER.error(
                                    f"Failed to convert hlo file {fp} to parquet, skipping upload.",
                                    exc_info=True,
                                )
                                msg = None
                    else:
                        # ``sp`` is already the record-relative POSIX form, which
                        # is exactly what the S3 key wants. This used to recompute
                        # it with ``fp.relative_to(prog.yml.targetdir)`` -- the
                        # call that raised ValueError for every sidecar written
                        # before the run trees were relocated.
                        file_s3_key = f"raw_data/{meta['action_uuid']}/{sp}"
                        msg = fp
                    LOGGER.debug(f"Destination: {file_s3_key}")
                    file_success = await self.to_s3(
                        msg=msg,
                        target=file_s3_key,
                        compress=compress,
                    )
                    if file_success:
                        LOGGER.debug("Removing file from pending list.")
                        prog.dict["files_pending"].remove(sp)
                        LOGGER.info(f"Adding file to S3 dict. {sp}: {file_s3_key}")
                        prog.dict["files_s3"].update({sp: file_s3_key})
                        LOGGER.debug(f"Updating progress: {prog.dict}")
                        prog.write_dict()

                        # update files list with uploaded filename
                        if fp.name != os.path.basename(file_s3_key):
                            file_idx = [
                                i
                                for i, x in enumerate(meta["files"])
                                if x["file_name"]
                                == str(fp.relative_to(prog.yml.targetdir))
                            ][0]
                            fileinfo = FileInfo.model_validate(
                                meta["files"].pop(file_idx)
                            )
                            fileinfo.file_name = str(
                                fp.relative_to(prog.yml.targetdir)
                            ).replace("\\", "/")
                            if "." in file_s3_key.split("/")[-1]:
                                fileinfo.file_name = os.path.basename(file_s3_key)
                            else:
                                fileinfo.file_name = fileinfo.file_name.replace(
                                    f"{fp.suffix}", ""
                                )
                            if fileinfo.file_type.endswith(
                                "helao__file"
                            ):  # generic file
                                fileinfo.file_type = fileinfo.file_type.replace(
                                    "helao__file",
                                    f"helao__{file_s3_key.split('.')[-1]}_file",
                                )
                            meta["files"].append(fileinfo.model_dump())

        # if prog.yml is an experiment first check processes before pushing to API
        if prog.yml.type == "experiment":
            LOGGER.debug(f"Finishing processes for {prog.yml.target.name}")
            # Rebuild process metas from the on-disk action ymls before flushing.
            # A reset/stale/cross-run .prg may have empty or partial
            # process_metas even though every child action already synced; this
            # recovers them so the experiment isn't stuck on "process index
            # ... missing".
            prog = self.reconcile_processes(prog)
            retry_count = 0
            s3_unf, api_unf = prog.list_unfinished_procs()
            while s3_unf or api_unf:
                if retry_count == retries:
                    break
                await self.sync_process(prog, force=True)
                s3_unf, api_unf = prog.list_unfinished_procs()
                retry_count += 1
            if s3_unf or api_unf:
                LOGGER.info(
                    f"Processes in {str(prog.yml.target)} did not sync after 3 tries."
                )
                return False
            if prog.dict["process_metas"]:
                meta["process_list"] = [
                    d["process_uuid"]
                    for _, d in sorted(prog.dict["process_metas"].items())
                ]

        LOGGER.debug(f"Patching model for {prog.yml.target.name}")
        patched_meta = {MOD_PATCH.get(k, k): v for k, v in meta.items()}
        meta = MOD_MAP[prog.yml.type](**patched_meta).clean_dict(strip_private=True)

        # patch technique lists in meta
        tech_name = meta.get("technique_name", "NA")
        if isinstance(tech_name, list):
            split_technique = tech_name[meta.get("action_split", 0)]
            meta["technique_name"] = split_technique

        # next push prog.yml to S3
        if not prog.s3_done or force_s3:
            LOGGER.debug(f"Pushing prog.yml->json to S3 for {prog.yml.target.name}")
            uuid_key = patched_meta[f"{prog.yml.type}_uuid"]
            meta_s3_key = f"{prog.yml.type}/{uuid_key}.json"
            s3_success = await self.to_s3(meta, meta_s3_key)
            if s3_success:
                prog.dict["s3"] = True
                prog.write_dict()

        # The API leg is retired: the SQL database is offline and to_api() was a
        # no-op stub. The flag is still set so the "s3_done and api_done" gate
        # below advances the run to RUNS_SYNCED.
        if not prog.api_done or force_api:
            prog.dict["api"] = True
            prog.write_dict()

        # get yml target name for popping later (after seq zip removes yml)
        yml_target_name = prog.yml.target.name
        yml_type = prog.yml.type

        # move to synced
        if prog.s3_done and prog.api_done:

            LOGGER.debug(f"Moving files to RUNS_SYNCED for {yml_target_name}")
            for lock_path in prog.yml.lock_files:
                lock_path.unlink()
            for file_path in prog.yml.misc_files + prog.yml.hlo_files:
                LOGGER.debug(f"Moving {str(file_path)}")
                move_success = await asyncio.to_thread(move_to_synced, file_path)
                while not move_success:
                    LOGGER.debug(f"{file_path} is in use, retrying.")
                    await asyncio.sleep(1)
                    move_success = await asyncio.to_thread(move_to_synced, file_path)

            # finally move yaml and update target
            LOGGER.debug(f"Moving {yml_target_name} to RUNS_SYNCED")
            # with prog.yml.filelock:
            yml_success = move_to_synced(yml_path)
            if yml_success:
                result = prog.yml.cleanup()
                LOGGER.debug(f"Cleanup {yml_target_name} {result}.")
                if result == "success":
                    LOGGER.debug("yml_success")
                    prog = self.get_progress(Path(yml_success))
                    LOGGER.debug("reassigning prog")
                    prog.dict["yml"] = str(yml_success)
                    LOGGER.debug("updating progress")
                    prog.write_dict()

            # pop children from progress dict
            if yml_type in ["experiment", "sequence"]:
                children = prog.yml.children
                LOGGER.debug(f"Removing children from progress: {children}.")
                for childyml in children:
                    LOGGER.debug(f"Clearing {childyml.target.name}")
                    finished_child_path = childyml.finished_path.parent
                    if finished_child_path.exists():
                        self.try_remove_empty(str(finished_child_path))
                self.try_remove_empty(str(prog.yml.finished_path.parent))

            if yml_type == "sequence":
                sequence_name = prog.yml.meta.get("sequence_name", "NA")
                LOGGER.debug(f"Zipping {prog.yml.target.parent.name}.")
                zip_target = prog.yml.target.parent.parent.joinpath(
                    f"{prog.yml.target.parent.name}.zip"
                )
                LOGGER.info(
                    f"Full sequence has synced, creating zip: {str(zip_target)}"
                )
                path_parts = prog.yml.target.parts
                await asyncio.to_thread(zip_dir, prog.yml.target.parent, zip_target)
                root_path = Path(
                    *path_parts[: path_parts.index(RunDir.SYNCED)]
                ).as_posix()
                self.cleanup_root(root_path)
                LOGGER.debug("Removing sequence from progress.")
                # self.progress.pop(prog.yml.target.name)

                if zip_target.exists() and sequence_name in self.auto_analyses:
                    ana_config = self.auto_analyses[sequence_name]
                    LOGGER.info(
                        f"dispatching auto-analysis {ana_config['endpoint']} for {sequence_name}"
                    )
                    await async_action_dispatcher(
                        world_config_dict={
                            "servers": {ana_config["server_key"]: ana_config}
                        },
                        A=Action(
                            action_name=ana_config["endpoint"],
                            action_server=MachineModel(
                                server_name=ana_config["server_key"],
                            ),
                            action_params={
                                "sequence_zip_path": str(zip_target),
                                "params": ana_config.get("analysis_params", {}),
                            },
                        ),
                    )

            if yml_target_name in self.running_tasks:
                LOGGER.debug(f"Removing {yml_target_name} from running_tasks.")
                async with self.aiolock:
                    self.running_tasks.pop(yml_target_name)

            # if action contributes processes, update processes
            if yml_type == "action" and meta.get("process_contrib", False):
                exp_prog = self.update_process(prog.yml, meta)
                await self.sync_process(exp_prog)

        return_dict = {k: d for k, d in prog.dict.items() if k != "process_metas"}
        return return_dict

    def update_process(self, act_yml: HelaoYml, act_meta: dict) -> Progress:
        """Fold a finished action into its parent experiment's process metadata.

        Determines which process group the action contributes to (handling
        the legacy "finisher index" path for experiments without an explicit
        ``process_groups``), merges ``process_contrib`` keys from the action
        into the process meta, deduplicates ``samples_in``/``samples_out``,
        and records the action in ``process_actions_done``.

        Args:
            act_yml: yml wrapper for the finished action.
            act_meta: Action metadata dict.

        Returns:
            The updated experiment ``Progress``.
        """
        exp_path = Path(act_yml.parent_path)
        exp_prog = self.get_progress(exp_path)
        # with exp_prog.prglock:
        act_idx = act_meta["action_order"]

        # Idempotency guard: skip an action whose contribution is already folded
        # into process_metas, so update_process is safe to replay (required for
        # reconcile_processes to rebuild from on-disk ymls after a reset or
        # cross-run resume). The guard keys on action_uuid, NOT action_order:
        # split actions (Base.split_action bumps action_split but keeps
        # action_order) produce several ymls sharing one action_order, each with
        # a distinct uuid and its own samples/files -- all must be folded.
        # process_actions_done stays order-keyed for the completion gate.
        act_uuid = act_meta.get("action_uuid")
        if act_uuid is not None:
            folded_uuids = {
                str(a.get("action_uuid"))
                for m in exp_prog.dict["process_metas"].values()
                for a in m.get("dispatched_actions_abbr", [])
            }
            if str(act_uuid) in folded_uuids:
                return exp_prog
        elif act_idx in exp_prog.dict["process_actions_done"]:
            return exp_prog

        # handle legacy experiments (no pre-declared process_order_groups)
        if exp_prog.dict["legacy_experiment"]:
            # if action is a process finisher, add to exp progress
            if act_meta["process_finish"]:
                exp_prog.dict["legacy_finisher_idxs"] = sorted(
                    set(exp_prog.dict["legacy_finisher_idxs"]).union([act_idx])
                )
            pf_idxs = exp_prog.dict["legacy_finisher_idxs"]
            pidx = (
                len(pf_idxs)
                if act_idx > max(pf_idxs + [-1])
                else pf_idxs.index(min(x for x in pf_idxs if x >= act_idx))
            )
            exp_prog.dict["process_groups"][pidx] = exp_prog.dict["process_groups"].get(
                pidx, []
            )
            if act_idx not in exp_prog.dict["process_groups"][pidx]:
                exp_prog.dict["process_groups"][pidx].append(act_idx)
            pidxs = [pidx]
        else:
            pidxs = [
                k for k, l in exp_prog.dict["process_groups"].items() if act_idx in l
            ]
            if not pidxs:
                # An executed action that belongs to no declared process group
                # contributes nothing; skip it rather than raising IndexError
                # (which would abort the whole syncer worker mid-experiment).
                LOGGER.warning(
                    f"Action order {act_idx} ({act_yml.target.name}) is not a member "
                    f"of any process group for {exp_prog.yml.target.name}; skipping "
                    f"process contribution."
                )
                return exp_prog
            if len(pidxs) > 1:
                # An action_order declared in more than one process group
                # contributes to EACH of them. Folding into only the first (the
                # old matches[0] behavior) left the other groups without a meta,
                # so sync_process found "actions but no meta" and the experiment
                # never finished. Fold into all matching groups.
                LOGGER.warning(
                    f"Action order {act_idx} ({act_yml.target.name}) belongs to "
                    f"multiple process groups {pidxs} in "
                    f"{exp_prog.yml.target.name}; folding into all of them."
                )

        # Build or extend the process meta for every group this action belongs
        # to. This runs for BOTH legacy and non-legacy experiments. The legacy
        # branch previously stopped after bucketing the action, never populating
        # process_metas, so a legacy experiment could never finish syncing --
        # sync_process looped forever on "process index {pidx} is missing".
        for pidx in pidxs:
            if pidx not in exp_prog.dict["process_metas"]:
                process_meta = {
                    k: v
                    for k, v in exp_prog.yml.meta.items()
                    if k
                    in [
                        "sequence_uuid",
                        "experiment_uuid",
                        "orchestrator",
                        "access",
                        "dummy",
                        "simulation",
                        "run_type",
                        "campaign_name",
                        "campaign_uuid",
                        "run_id",
                    ]
                }
                if "data_request_id" in exp_prog.yml.meta:
                    process_meta["data_request_id"] = exp_prog.yml.meta[
                        "data_request_id"
                    ]
                process_meta["process_params"] = exp_prog.yml.meta.get(
                    "experiment_params", {}
                )
                process_meta["technique_name"] = exp_prog.yml.meta.get(
                    "technique_name", exp_prog.yml.meta["experiment_name"]
                )
                process_list = exp_prog.yml.meta.get("process_list", [])
                process_input_str = f"{exp_prog.yml.meta['experiment_uuid']}__{pidx}"
                process_uuid = (
                    process_list[pidx]
                    if process_list
                    else str(gen_uuid(process_input_str))
                )
                process_meta["process_uuid"] = process_uuid
                process_meta["process_group_index"] = pidx
                process_meta["dispatched_actions_abbr"] = []
            else:
                process_meta = exp_prog.dict["process_metas"][pidx]

            # fold this action into the process meta
            process_meta["dispatched_actions_abbr"].append(
                ShortActionModel.model_validate(act_meta).clean_dict(strip_private=True)
            )
            if act_idx == min(exp_prog.dict["process_groups"][pidx]):
                process_meta["process_timestamp"] = act_meta["action_timestamp"]
            if "technique_name" in act_meta:
                process_meta["technique_name"] = act_meta["technique_name"]
            tech_name = process_meta["technique_name"]
            if isinstance(tech_name, list):
                split_technique = tech_name[act_meta.get("action_split", 0)]
                process_meta["technique_name"] = split_technique
            for pc in act_meta["process_contrib"]:
                if pc not in act_meta:
                    continue
                contrib = act_meta[pc]
                new_name = pc.replace("action_", "process_")
                if new_name not in process_meta:
                    # copy mutable contribs so multiple groups (and repeated
                    # folds) never alias the same list/dict object
                    process_meta[new_name] = (
                        copy(contrib) if isinstance(contrib, (list, dict)) else contrib
                    )
                elif isinstance(contrib, dict):
                    process_meta[new_name].update(contrib)
                elif isinstance(contrib, list):
                    process_meta[new_name] += contrib
                else:
                    process_meta[new_name] = contrib
                # deduplicate sample lists
                if new_name in ["samples_in", "samples_out"]:
                    actuuid_order = {
                        x["action_uuid"]: x["orch_submit_order"]
                        for x in process_meta["dispatched_actions_abbr"]
                    }
                    sample_list = process_meta[new_name]
                    dedupe_dict = defaultdict(list)
                    deduped_samples = []
                    for si, x in enumerate(sample_list):
                        sample_label = x.get("global_label", False)
                        if not sample_label:
                            continue
                        actuuid = [
                            y for y in x["action_uuid"] if y in actuuid_order.keys()
                        ]
                        if not actuuid:
                            actorder = si
                        else:
                            actorder = actuuid_order[actuuid[0]]
                        dedupe_dict[sample_label].append((actorder, si))
                    if new_name == "samples_in":
                        deduped_samples = [
                            sample_list[min(v)[1]] for v in dedupe_dict.values()
                        ]
                    elif new_name == "samples_out":
                        deduped_samples = [
                            sample_list[max(v)[1]] for v in dedupe_dict.values()
                        ]
                    if deduped_samples:
                        process_meta[new_name] = deduped_samples
            exp_prog.dict["process_metas"][pidx] = process_meta

        # register finished action in process_actions_done {order: ymltargetname}
        exp_prog.dict["process_actions_done"].update({act_idx: act_yml.target.name})
        exp_prog.write_dict()
        return exp_prog

    def reconcile_processes(self, exp_prog: Progress) -> Progress:
        """Rebuild an experiment's process bookkeeping from its on-disk actions.

        ``process_metas`` / ``process_actions_done`` are accumulated one action
        at a time as each child syncs, and live only in the experiment's
        ``.prg``. That state is lost whenever the ``.prg`` is reset or recreated
        -- after a partial sync, a ``reset_sync``, or a cross-run resume where
        the contributing actions already moved to ``RUNS_SYNCED`` and so are
        never re-enqueued (``list_pending_acts`` only scans ``RUNS_FINISHED``).
        A fresh ``.prg`` then has empty ``process_metas`` and the experiment can
        never finish syncing.

        This replays every child action yml found on disk (any status) through
        :meth:`update_process`, which is idempotent, so the process metadata is
        reconstructed from the authoritative source instead of being lost.

        Args:
            exp_prog: Experiment progress to reconcile.

        Returns:
            The reconciled experiment ``Progress`` (a fresh object).
        """
        if exp_prog.yml.type != "experiment":
            return exp_prog
        for child in exp_prog.yml.children:
            if child.type != "action":
                continue
            child_meta = child.meta
            if not child_meta.get("process_contrib", False):
                continue
            exp_prog = self.update_process(child, child_meta)
        return exp_prog

    async def sync_process(self, exp_prog: Progress, force: bool = False) -> Progress:
        """Push pending processes for an experiment to S3 and the API.

        For each process group not yet flagged in ``process_s3`` /
        ``process_api`` and whose contributing actions are complete (or when
        ``force`` is true), writes a local ``*-prc.yml``, uploads the JSON to
        S3, and registers it with the API.

        Args:
            exp_prog: Experiment progress to process.
            force: Push even if the usual completion conditions aren't met.

        Returns:
            The same ``exp_prog`` with updated ``process_s3`` / ``process_api`` lists.
        """
        s3_unfinished, api_unfinished = exp_prog.list_unfinished_procs()
        for pidx in s3_unfinished:
            pidx = pidx
            gids = exp_prog.dict["process_groups"][pidx]
            push_condition = False
            if force:
                push_condition = force
            elif exp_prog.dict["legacy_experiment"]:
                push_condition = max(gids) in exp_prog.dict[
                    "legacy_finisher_idxs"
                ] and all(i in exp_prog.dict["process_actions_done"] for i in gids)
            else:
                push_condition = (
                    all(i in exp_prog.dict["process_actions_done"] for i in gids)
                    and exp_prog.dict["process_metas"].get(pidx, {}) != {}
                )

            if push_condition:
                if pidx not in exp_prog.dict["process_metas"]:
                    # No process meta even after reconcile_processes replayed
                    # every on-disk action. Decide by whether any contributing
                    # action actually exists for this group.
                    gids = exp_prog.dict["process_groups"].get(pidx, [])
                    done_gids = [
                        i for i in gids if i in exp_prog.dict["process_actions_done"]
                    ]
                    if not done_gids:
                        # Phantom group: declared in process_order_groups at
                        # orch plan time, but its contributing action was never
                        # dispatched/synced (skipped or removed from the queue).
                        # Drop it so the experiment can finish instead of looping
                        # on reset_sync + re-enqueue forever.
                        LOGGER.warning(
                            f"Process group {pidx} in {str(exp_prog.yml.target)} has "
                            f"no contributing actions on disk; dropping it so the "
                            f"experiment can finish."
                        )
                        exp_prog.dict["process_groups"].pop(pidx, None)
                        if pidx not in exp_prog.dict["process_s3"]:
                            exp_prog.dict["process_s3"].append(pidx)
                        if pidx not in exp_prog.dict["process_api"]:
                            exp_prog.dict["process_api"].append(pidx)
                        exp_prog.write_dict()
                        continue
                    # Contributing actions are recorded, but their meta is
                    # missing after reconcile replayed everything on disk. Whether
                    # that is retryable depends entirely on whether any of those
                    # actions is still *readable*, because the action yml is the
                    # only thing a meta can be rebuilt from.
                    on_disk = {
                        c.meta.get("action_order")
                        for c in exp_prog.yml.children
                        if c.type == "action"
                    }
                    if set(done_gids) & on_disk:
                        # Rebuildable: an action is there and reconcile still did
                        # not produce a meta, so something else went wrong on this
                        # pass. Skip rather than wiping and re-queuing the whole
                        # subtree; the next pass can legitimately succeed.
                        LOGGER.error(
                            f"Process group {pidx} in {str(exp_prog.yml.target)} has "
                            f"contributing actions {done_gids} on disk but no process "
                            f"meta after reconcile; skipping this pass."
                        )
                        continue
                    # Unrebuildable: process_actions_done records actions whose
                    # ymls have left every tree HelaoYml.children scans (they
                    # synced and were swept into the zipped sequence), so no pass
                    # will ever rebuild this meta. Leaving it unfinished is what
                    # kept such experiments in a permanent re-enqueue loop --
                    # sync_yml returns False forever and anything that touches the
                    # experiment starts it again. Park it exactly as a phantom
                    # group is parked, but alert rather than warn: a process that
                    # existed is being written off, which is a data-completeness
                    # loss a human needs to see, not a bookkeeping tidy-up.
                    # ``alert`` is installed onto Logger by helao_logging with a
                    # setattr, which static analysis cannot see.
                    LOGGER.alert(  # type: ignore[attr-defined]
                        f"Process group {pidx} in {str(exp_prog.yml.target)} records "
                        f"contributing actions {done_gids} whose ymls are no longer on "
                        f"disk and whose process meta is gone; it cannot be rebuilt. "
                        f"Parking the group so the experiment can finish -- this "
                        f"process will NOT be uploaded. Recover it by restoring the "
                        f"action ymls to RUNS_FINISHED and re-running finish_yml."
                    )
                    exp_prog.dict["process_groups"].pop(pidx, None)
                    if pidx not in exp_prog.dict["process_s3"]:
                        exp_prog.dict["process_s3"].append(pidx)
                    if pidx not in exp_prog.dict["process_api"]:
                        exp_prog.dict["process_api"].append(pidx)
                    exp_prog.write_dict()
                    continue
                meta = exp_prog.dict["process_metas"][pidx]
                uuid_key = meta["process_uuid"]
                model = ProcessModel.model_validate(meta).clean_dict(strip_private=True)
                # write to local yml
                save_dir = os.path.dirname(
                    os.path.join(
                        self.helaodirs.process_root,
                        exp_prog.yml.relative_path,
                    )
                )
                save_yml_path = os.path.join(
                    save_dir, f"{pidx}__{uuid_key}__{meta['technique_name']}-prc.yml"
                )
                os.makedirs(save_dir, exist_ok=True)
                with open(save_yml_path, "w") as f:
                    f.write(yml_dumps(model))
                # sync to s3
                meta_s3_key = f"process/{uuid_key}.json"
                s3_success = await self.to_s3(model, meta_s3_key)
                if s3_success:
                    exp_prog.dict["process_s3"].append(pidx)
                    exp_prog.write_dict()
        for pidx in api_unfinished:
            gids = exp_prog.dict["process_groups"].get(pidx)
            # a group dropped as phantom in the s3 loop above is gone from
            # process_groups; skip it here too (its pidx was already flagged done)
            if gids is None or pidx not in exp_prog.dict["process_metas"]:
                continue
            if all(i in exp_prog.dict["process_actions_done"] for i in gids):
                meta = exp_prog.dict["process_metas"][pidx]
                # The API push is retired (see sync_yml), but the meta is still
                # validated here so a malformed process fails loudly instead of
                # being marked done.
                ProcessModel.model_validate(meta)
                exp_prog.dict["process_api"].append(pidx)
                exp_prog.write_dict()
        return exp_prog

    async def to_s3(
        self,
        msg: Union[dict, Path],
        target: str,
        retries: int = 5,
        compress: bool = False,
    ) -> bool:
        """Upload a dict (as JSON) or a file to the configured S3 bucket.

        Args:
            msg: Dict to serialize to JSON, or file path to upload as-is.
            target: Destination key inside the bucket.
            retries: Number of retries (each waits 30s) before giving up.
            compress: If ``msg`` is a dict, gzip it and append ``.gz`` to ``target``.

        Returns:
            True on successful upload (or when S3 is not configured at all),
            False if all retries failed.
        """
        try:
            if self.s3 is None:
                LOGGER.info("S3 is not configured. Skipping to S3 upload.")
                return True
            if isinstance(msg, dict):
                LOGGER.debug("Converting dict to json.")
                uploadee = dict2json(msg)
                uploader = self.s3.upload_fileobj
                if compress:
                    if not target.endswith(".gz"):
                        target = f"{target}.gz"
                    buffer = io.BytesIO()
                    with gzip.GzipFile(fileobj=buffer, mode="wb") as f:
                        f.write(uploadee.read())
                    buffer.seek(0)
                    uploadee = buffer
            else:
                LOGGER.debug("Converting path to str")
                uploadee = str(msg)
                uploader = self.s3.upload_file
            for i in range(retries + 1):
                if i > 0:
                    LOGGER.info(f"S3 retry [{i}/{retries}]: {self.bucket}, {target}")
                try:
                    await asyncio.to_thread(uploader, uploadee, self.bucket, target)
                    return True
                except Exception:
                    LOGGER.error(
                        f"Failed to upload {target} to S3, retrying in 30 seconds",
                        exc_info=True,
                    )
                    await asyncio.sleep(30)
            LOGGER.info(f"Did not upload {target} after {retries} tries.")
            return False
        except Exception:
            LOGGER.error(f"Could not push {target}.", exc_info=True)
            return False

    def list_pending(self, omit_manual_exps: bool = True) -> list:
        """Return ``*-seq.yml`` paths waiting under ``RUNS_FINISHED``.

        Args:
            omit_manual_exps: Skip files containing ``manual_orch_seq``.

        Returns:
            List of pending sequence yml file paths.
        """
        finished_dir = str(self.helaodirs.save_root).replace(
            RunDir.ACTIVE.value, RunDir.FINISHED.value
        )
        pending = glob(os.path.join(finished_dir, "*", "*", "*", "*-seq.yml"))
        if omit_manual_exps:
            pending = [x for x in pending if "manual_orch_seq" not in x]
        LOGGER.info(f"Found {len(pending)} pending sequences in RUNS_FINISHED.")
        return pending

    def list_pending_acts(self, omit_manual_exps: bool = True) -> list:
        """Return ``*-act.yml`` paths waiting under ``RUNS_FINISHED``.

        Args:
            omit_manual_exps: Skip files containing ``manual_orch_seq``.

        Returns:
            List of pending action yml file paths.
        """
        finished_dir = str(self.helaodirs.save_root).replace(
            RunDir.ACTIVE.value, RunDir.FINISHED.value
        )
        pending = glob(os.path.join(finished_dir, "*", "*", "*", "*", "*", "*-act.yml"))
        if omit_manual_exps:
            pending = [x for x in pending if "manual_orch_seq" not in x]
        LOGGER.info(f"Found {len(pending)} pending actions in RUNS_FINISHED.")
        return pending

    def list_pending_exps(self, omit_manual_exps: bool = True) -> list:
        """Return ``*-exp.yml`` paths waiting under ``RUNS_FINISHED``.

        Args:
            omit_manual_exps: Skip files containing ``manual_orch_seq``.

        Returns:
            List of pending experiment yml file paths.
        """
        finished_dir = str(self.helaodirs.save_root).replace(
            RunDir.ACTIVE.value, RunDir.FINISHED.value
        )
        pending = glob(os.path.join(finished_dir, "*", "*", "*", "*", "*-exp.yml"))
        if omit_manual_exps:
            pending = [x for x in pending if "manual_orch_seq" not in x]
        LOGGER.info(f"Found {len(pending)} pending experiments in RUNS_FINISHED.")
        return pending

    async def finish_pending(
        self, omit_manual_exps: bool = True, actions_first: bool = False
    ) -> list:
        """Enqueue every pending sequence (and optionally actions/experiments first).

        For each pending yml, any existing ``.progress`` sibling under
        ``RUNS_SYNCED`` triggers :meth:`reset_sync` before the yml is queued.

        **That reset is dead for anything this build writes, deliberately so.**
        :class:`Progress` writes ``.prg``; ``.progress`` is the legacy sidecar
        name, kept only in :meth:`reset_sync`'s and :meth:`unsync_dir`'s delete
        filters. So a yml queued from here keeps its ``.prg`` and *resumes*.
        Widening the test to ``.prg`` would invert that: every partially synced
        run would be reset instead, discarding recorded S3/API progress and
        re-uploading it all -- on a share holding a backlog of pending sequences
        that is the expensive wrong answer, not a safety net.
        Nor is it needed. The failure a reset was reached for -- a ``.prg`` whose
        ``process_actions_done`` records actions whose ``process_metas`` entries
        are gone -- is repaired in place by :meth:`sync_process`, which parks a
        group it can no longer rebuild instead of retrying it forever. A diverged
        sidecar therefore resolves on its next pass without anything being thrown
        away.

        Args:
            omit_manual_exps: Skip files containing ``manual_orch_seq``.
            actions_first: When true, enqueue actions and experiments before
                sequences (used to drain a partial sync).

        Returns:
            The list of pending sequence paths that were enqueued.
        """

        async def reset_and_queue(pp, rank: int = 0):
            """Reset a stale legacy ``.progress`` sibling, then enqueue ``pp``.

            Legacy artifacts only -- see the caller's docstring for why this does
            not (and must not) look for ``.prg``.
            """
            if os.path.exists(
                pp.replace(RunDir.FINISHED.value, RunDir.SYNCED.value).replace(
                    ".yml", ".progress"
                )
            ):
                self.reset_sync(
                    os.path.dirname(pp).replace(
                        RunDir.FINISHED.value, RunDir.SYNCED.value
                    )
                )
            await self.enqueue_yml(pp, rank)

        if actions_first:
            pending_acts = self.list_pending_acts(omit_manual_exps)
            LOGGER.info(f"Enqueueing {len(pending_acts)} actions from RUNS_FINISHED.")
            for pp in pending_acts:
                await reset_and_queue(pp, rank=0)

            pending_exps = self.list_pending_exps(omit_manual_exps)
            LOGGER.info(
                f"Enqueueing {len(pending_exps)} experiments from RUNS_FINISHED."
            )
            for pp in pending_exps:
                await reset_and_queue(pp, rank=1)

        pending_seqs = self.list_pending(omit_manual_exps)
        LOGGER.info(f"Enqueueing {len(pending_seqs)} sequences from RUNS_FINISHED.")

        for pp in pending_seqs:
            await reset_and_queue(pp, rank=2)

        return pending_seqs

    def reset_sync(self, sync_path: str) -> bool:
        """Revert a synced sequence (zip or directory) back to ``RUNS_FINISHED``.

        For a synced sequence ``.zip``, the contents (minus ``.prg`` / ``.lock``
        entries) are extracted into the parallel ``RUNS_FINISHED`` directory
        and the zip is renamed to ``.orig``. For an unzipped ``RUNS_SYNCED``
        directory, ``.prg``/``.progress``/``.lock`` files are deleted and the
        remaining files are moved back to ``RUNS_FINISHED``.

        Args:
            sync_path: Path to a synced sequence zip or directory.

        Returns:
            True on a successful reset, False otherwise.
        """
        if not os.path.exists(sync_path):
            LOGGER.info(f"{sync_path} does not exist.")
            return False
        if RunDir.SYNCED not in sync_path:
            LOGGER.info(f"Cannot reset path that's not in RUNS_SYNCED: {sync_path}")
            return False
        ## if path is a zip
        if sync_path.endswith(".zip"):
            zf = ZipFile(sync_path)
            if any(x.endswith("-seq.prg") for x in zf.namelist()):
                seqzip_dir = os.path.dirname(sync_path)
                dest = os.path.join(
                    seqzip_dir.replace(RunDir.SYNCED.value, RunDir.FINISHED.value),
                    os.path.basename(sync_path).replace(".zip", ""),
                )
                os.makedirs(dest, exist_ok=True)
                no_lock_prg = [
                    x
                    for x in zf.namelist()
                    if not x.endswith(".prg") and not x.endswith(".lock")
                ]
                zf.extractall(dest, members=no_lock_prg)
                zf.close()
                if not os.path.exists(sync_path.replace(".zip", ".orig")):
                    shutil.move(sync_path, sync_path.replace(".zip", ".orig"))
                LOGGER.info(f"Restored zip to {dest}")
                return True
            zf.close()
            LOGGER.info("Zip does not contain a valid sequence.")
            return False

        ## if path is a directory
        elif os.path.isdir(sync_path):
            base_prgs = [
                x
                for x in glob(os.path.join(sync_path, "**", "*-*.pr*"), recursive=True)
                if x.endswith(".progress") or x.endswith(".prg") or x.endswith(".lock")
            ]
            # seq_prgs = [x for x in base_prgs if "-seq.pr" in x]
            # for x in seq_prgs:
            #     base_prgs = [
            #         y for y in base_prgs if not y.startswith(os.path.dirname(x))
            #     ]
            # exp_prgs = [x for x in base_prgs if "-exp.pr" in x]
            # for x in exp_prgs:
            #     base_prgs = [
            #         y for y in base_prgs if not y.startswith(os.path.dirname(x))
            #     ]
            # act_prgs = [x for x in base_prgs if "-act.pr" in x]
            # for x in act_prgs:
            #     base_prgs = [
            #         y for y in base_prgs if not y.startswith(os.path.dirname(x))
            #     ]

            # base_prgs = act_prgs + exp_prgs + seq_prgs

            if not base_prgs:
                LOGGER.info(
                    f"Did not find any .prg or .progress files in subdirectories of {sync_path}"
                )
                self.unsync_dir(sync_path)

            else:
                LOGGER.warning(
                    f"Found {len(base_prgs)} .prg, .progress, or .lock files in subdirectories of {sync_path}"
                )
                # remove all .prg files and lock files
                for prg in base_prgs:
                    base_dir = os.path.dirname(prg)
                    sub_prgs = [
                        x
                        for x in glob(
                            os.path.join(base_dir, "**", "*-*.pr*"), recursive=True
                        )
                        if x.endswith(".progress") or x.endswith(".prg")
                    ]
                    sub_lock = [
                        x
                        for x in glob(
                            os.path.join(base_dir, "**", "*.lock"), recursive=True
                        )
                    ]
                    LOGGER.info(
                        f"Removing {len(base_prgs) + len(sub_lock)} prg and progress files in subdirectories of {base_dir}"
                    )
                    for sp in sub_prgs + sub_lock:
                        os.remove(sp)

                    # move path back to RUNS_FINISHED
                    self.unsync_dir(base_dir)

            seq_zips = glob(os.path.join(sync_path, "**", "*.zip"), recursive=True)
            if not seq_zips:
                LOGGER.info(
                    f"Did not find any zip files in subdirectories of {sync_path}"
                )
            else:
                LOGGER.info(
                    f"Found {len(seq_zips)} zip files in subdirectories of {sync_path}"
                )
                for seq_zip in seq_zips:
                    self.reset_sync(seq_zip)
            return True
        LOGGER.info("Arg was not a sequence path or zip.")
        return False

    def shutdown(self):
        """Hook for graceful shutdown; currently a no-op."""
        pass

    def unsync_dir(self, sync_dir: str):
        """Delete progress/lock files and move the rest from ``sync_dir`` to ``RUNS_FINISHED``.

        Args:
            sync_dir: Directory under ``RUNS_SYNCED`` to unsync.
        """
        for fp in glob(os.path.join(sync_dir, "**", "*"), recursive=True):
            if fp.endswith(".lock") or fp.endswith(".progress") or fp.endswith(".prg"):
                os.remove(fp)
            elif not os.path.isdir(fp):
                tp = os.path.dirname(
                    fp.replace(RunDir.SYNCED.value, RunDir.FINISHED.value)
                )
                os.makedirs(tp, exist_ok=True)
                shutil.move(fp, tp)
        LOGGER.warning(f"Successfully reverted {sync_dir}")


class HelaoSyncer(SyncDriver):
    """``SyncDriver`` variant that gets its config from a running HELAO host.

    The constructor pulls ``params`` from the action server's own
    ``server_cfg`` first, falling back to the global ``servers[sync_server_name]``
    block when no AWS path is set locally.

    Attributes:
        base: Server instance this syncer is attached to.
    """

    base: "ActionHost"

    def __init__(
        self, action_serv: "ActionHost", sync_server_name: Optional[str] = None
    ):
        """Pick up driver params from ``action_serv`` and initialize ``SyncDriver``.

        Args:
            action_serv: Action/orchestrator server whose ``server_cfg`` /
                ``world_cfg`` supplies syncer configuration.
            sync_server_name: Server key to fall back to when local params lack
                an ``aws_config_path``. Defaults to whichever of ``SYNC`` or the
                legacy ``DB`` alias the group defines.
        """
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.world_config = action_serv.world_cfg
        # to load this driver on orch, we resolve the syncer server key (SYNC,
        # or the legacy DB alias) or take a manually-specified key
        resolved_key = resolve_sync_server_key(
            self.world_config, preferred=sync_server_name
        )
        if not self.config_dict.get("aws_config_path", False) and resolved_key:
            self.config_dict = self.world_config["servers"][resolved_key].get(
                "params", {}
            )
        LOGGER.info("initializing SyncDriver")
        super().__init__(self.config_dict, self.base.helaodirs)
