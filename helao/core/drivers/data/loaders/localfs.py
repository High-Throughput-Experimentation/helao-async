"""Local-filesystem variant of the HELAO data loader.

Indexes ``*-{seq,exp,act,prc}.yml`` files under a run tree (active, finished,
synced, or diag) or a synced sequence ``.zip`` archive into pandas dataframes,
and exposes ``LocalLoader`` + per-record wrappers that read YAML/HLO/parquet
content via :class:`helao.helpers.file_mapper.FileMapper`.
"""

import os
from io import BytesIO
from glob import glob
from uuid import UUID
from datetime import datetime
from zipfile import ZipFile
from typing import Optional

import pandas as pd

from helao.helpers.yml_tools import yml_load
from helao.helpers.file_mapper import FileMapper
from helao.helpers.hlo_data import read_hlo_bytes
from helao.core.drivers.data.loaders.model_base import HelaoDataModelMixin
from helao.core.models.run_dir import RunDir


def parse_seq_path(ymlp, target) -> tuple:
    """Parse sequence path components from a yml path and its containing target.

    Extracts the timestamp, sequence name, label, plate id (when the trailing
    serial digits checksum), sample number, and the original directory name.

    Args:
        ymlp: Path to the ``-seq.yml`` file (or its parent dir).
        target: Path of the containing target (a directory or ``.zip``).

    Returns:
        ``(timestamp, seq_name, seq_lab, plate_id, sample_no, yml_dir, ymlp)``.
    """
    if ymlp.endswith(".yml") or target.endswith(".zip"):
        yml_dir = os.path.basename(os.path.dirname(ymlp))
        yml_file = os.path.basename(ymlp)
        if target.endswith(".zip"):
            # Legacy single-sequence zips store the seq yml at the archive root
            # (no parent dir), so fall back to the zip filename. MicroOrch zips
            # are rooted at RUNS_FINISHED, so the entry's own parent dir IS the
            # sequence dir and must be used.
            entry_dir = os.path.basename(os.path.dirname(ymlp))
            if entry_dir:
                yml_dir = entry_dir
            else:
                yml_dir = os.path.basename(target).replace(".zip", "")
            yml_file = os.path.basename(ymlp)
    else:
        yml_dir = os.path.basename(ymlp)
        yml_file = yml_dir
    seq_path_parts = yml_dir.split("__")
    seq_name = seq_path_parts[1]
    seq_lab = "__".join(seq_path_parts[2:])
    plate_id = -1
    serial_parts = seq_lab.split("-")
    check_serial = None
    sample_no = None
    try:
        if serial_parts[-2].isdigit() and len(serial_parts) > 2:
            check_serial = serial_parts[-2]
            if serial_parts[-1].isdigit():
                sample_no = int(serial_parts[-1])
        elif serial_parts[-1].isdigit() and len(serial_parts) > 1:
            check_serial = serial_parts[-1]
    except Exception:
        print("could not parse serial parts:", serial_parts)
    if check_serial is not None:
        plate_str = check_serial[:-1]
        checksum = check_serial[-1]
        if sum([int(x) for x in plate_str]) % 10 == int(checksum):
            plate_id = int(plate_str)
            seq_lab = seq_lab.split("-")[0]
    try:
        timestamp = datetime.strptime(yml_file.split("-")[0], "%y%m%d.%H%M%S%f")
    except ValueError:
        timestamp = datetime.strptime(yml_file.split("-")[0], "%Y%m%d.%H%M%S%f")
    return timestamp, seq_name, seq_lab, plate_id, sample_no, yml_dir, ymlp


def parse_exp_path(ymlp) -> tuple:
    """Parse experiment path components from a ``-exp.yml`` path.

    Args:
        ymlp: Path to the ``-exp.yml`` file (or its parent dir).

    Returns:
        ``(timestamp, exp_name, yml_dir, ymlp)``.
    """
    if ymlp.endswith(".yml"):
        yml_dir = os.path.basename(os.path.dirname(ymlp))
    else:
        yml_dir = os.path.basename(ymlp)
    _, exp_name = yml_dir.split("__")
    yml_file = os.path.basename(ymlp)
    try:
        timestamp = datetime.strptime(yml_file.split("-")[0], "%y%m%d.%H%M%S%f")
    except ValueError:
        timestamp = datetime.strptime(yml_file.split("-")[0], "%Y%m%d.%H%M%S%f")
    return timestamp, exp_name, yml_dir, ymlp


def parse_act_path(ymlp) -> tuple:
    """Parse action path components from a ``-act.yml`` path.

    Args:
        ymlp: Path to the ``-act.yml`` file (or its parent dir).

    Returns:
        ``(timestamp, act_order, act_split, server_name, act_name, yml_dir, ymlp)``.

    Raises:
        ValueError: If the directory name does not split into 4 or 5 fields.
    """
    if ymlp.endswith(".yml"):
        yml_dir = os.path.basename(os.path.dirname(ymlp))
    else:
        yml_dir = os.path.basename(ymlp)
    path_parts = yml_dir.split("__")
    if len(path_parts) == 5:
        act_order, act_split, _, server_name, act_name = path_parts
    elif len(path_parts) == 4:
        act_order, act_split, server_name, act_name = path_parts
    else:
        raise ValueError(f"could not parse action path parts: {path_parts}")
    yml_file = os.path.basename(ymlp)
    try:
        timestamp = datetime.strptime(yml_file.split("-")[0], "%y%m%d.%H%M%S%f")
    except ValueError:
        timestamp = datetime.strptime(yml_file.split("-")[0], "%Y%m%d.%H%M%S%f")
    return timestamp, act_order, act_split, server_name, act_name, yml_dir, ymlp


def parse_prc_path(ymlp) -> tuple:
    """Parse process path components from a ``-prc.yml`` path.

    Args:
        ymlp: Path to the ``-prc.yml`` file.

    Returns:
        ``(prc_idx, prc_uuid, technique_name, yml_dir, ymlp, exp_timestamp, exp_name)``.
    """
    yml_dir = os.path.basename(os.path.dirname(ymlp))
    _, exp_name = yml_dir.split("__")
    yml_file = os.path.basename(ymlp)
    idx, prc_uuid, techname = yml_file.replace("-prc.yml", "").split("__")
    prc_uuid = UUID(prc_uuid)
    prc_idx = int(idx)
    try:
        exp_timestamp = datetime.strptime(yml_dir.split("__")[0], "%y%m%d.%H%M%S%f")
    except ValueError:
        exp_timestamp = datetime.strptime(yml_dir.split("__")[0], "%Y%m%d.%H%M%S%f")
    return prc_idx, prc_uuid, techname, yml_dir, ymlp, exp_timestamp, exp_name


class LocalLoader:
    """Loader for local HELAO run data (loose directories or a synced ``.zip``).

    Scans ``data_path`` (plus its sibling active/finished/synced/diag trees and
    the matching ``PROCESSES`` tree, or the contents of a ``.zip`` archive)
    for ``*-{seq,exp,act,prc}.yml`` files and indexes them into the
    ``sequences``/``experiments``/``actions``/``processes`` dataframes. Caches
    parsed yml dicts per path to avoid re-reading.

    Attributes:
        act_cache: Cached action yml dicts, keyed by file path.
        exp_cache: Cached experiment yml dicts, keyed by file path.
        seq_cache: Cached sequence yml dicts, keyed by file path.
        prc_cache: Cached process yml dicts, keyed by file path.
        target: Base directory or zip file being indexed.
        sequences: Sequence metadata frame.
        experiments: Experiment metadata frame.
        actions: Action metadata frame (joined to its experiment).
        processes: Process metadata frame.
    """

    def __init__(self, data_path: str):
        """Index every yml under ``data_path`` (or inside the zip) into dataframes.

        Args:
            data_path: Path to a ``RUNS_*`` directory tree or a synced sequence
                ``.zip`` file.

        Raises:
            FileNotFoundError: If ``data_path`` does not exist.
        """
        self.act_cache = {}  # {uuid: json_dict}
        self.exp_cache = {}
        self.seq_cache = {}
        self.prc_cache = {}
        self._yml_paths = {}
        self.target = os.path.abspath(os.path.normpath(data_path.strip('"').strip("'")))
        target_state = self.target.split("RUNS_")[-1].split(os.sep)[0]
        states = (
            RunDir.ACTIVE.value,
            RunDir.FINISHED.value,
            RunDir.SYNCED.value,
            RunDir.DIAG.value,
        )
        state_dir = f"RUNS_{target_state}"
        if self.target.endswith(".zip"):
            process_dir = self.target.replace(state_dir, "PROCESSES").replace(
                ".zip", ""
            )
        else:
            process_dir = os.path.dirname(self.target).replace(state_dir, "PROCESSES")
        check_dirs = [f"{self.target.replace(state_dir, x)}" for x in states] + [
            process_dir
        ]
        if not os.path.exists(self.target):
            raise FileNotFoundError(
                "data_path argument is not a valid file or folder path"
            )
        _yml_paths = []
        # MicroOrch zips are rooted at RUNS_FINISHED (arcnames keep the sequence
        # dir prefix) and carry a MANIFEST.txt at the archive root. Regular Orch
        # sequence zips are rooted at the sequence itself (no seq_dir prefix) and
        # have no MANIFEST. This flag disambiguates the two in get_bytes.
        self._is_microorch_zip = False
        if self.target.endswith(".zip"):
            with ZipFile(self.target, "r") as zf:
                zip_contents = zf.namelist()
            self._is_microorch_zip = "MANIFEST.txt" in zip_contents
            _yml_paths = [x for x in zip_contents if x.endswith(".yml")]
            _yml_paths += glob(
                os.path.join(process_dir, "**", "*-prc.yml"), recursive=True
            )
        elif os.path.isdir(self.target):
            for check_dir in check_dirs:
                _yml_paths += glob(
                    os.path.join(check_dir, "**", "*.yml"), recursive=True
                )
        else:
            for check_dir in check_dirs:
                _yml_paths += glob(
                    os.path.join(os.path.dirname(check_dir), "**", "*.yml"),
                    recursive=True,
                )

        for suffix in ("seq", "exp", "act", "prc"):
            self._yml_paths[suffix] = [
                x for x in _yml_paths if x.endswith(f"-{suffix}.yml")
            ]

        seq_parts = []
        for ymlp in self._yml_paths["seq"]:
            seq_parts.append(parse_seq_path(ymlp, self.target))
        self.sequences = pd.DataFrame(
            seq_parts,
            columns=[
                "sequence_timestamp",
                "sequence_name",
                "sequence_label",
                "plate_id",
                "sample_no",
                "sequence_dir",
                "sequence_localpath",
            ],
        )

        exp_parts = []
        for ymlp in self._yml_paths["exp"]:
            exp_parts.append(parse_exp_path(ymlp))
        self.experiments = pd.DataFrame(
            exp_parts,
            columns=[
                "experiment_timestamp",
                "experiment_name",
                "experiment_dir",
                "experiment_localpath",
            ],
        )

        act_parts = []
        for ymlp in self._yml_paths["act"]:
            act_parts.append(parse_act_path(ymlp))
        self.actions = pd.DataFrame(
            act_parts,
            columns=[
                "action_timestamp",
                "action_order",
                "action_split",
                "action_server",
                "action_name",
                "action_dir",
                "action_localpath",
            ],
        )

        prc_parts = []
        for ymlp in self._yml_paths["prc"]:

            prc_idx, prc_uuid, techname, yml_dir, ymlp, exp_timestamp, exp_name = (
                parse_prc_path(ymlp)
            )
            prc_parts.append(
                (
                    prc_idx,
                    prc_uuid,
                    techname,
                    yml_dir,
                    ymlp,
                    exp_timestamp,
                    exp_name,
                )
            )
        self.processes = pd.DataFrame(
            prc_parts,
            columns=[
                "process_group_index",
                "process_uuid",
                "technique_name",
                "process_dir",
                "process_localpath",
                "experiment_timestamp",
                "experiment_name",
            ],
        )

        self.actions["experiment_index"] = self.actions.action_localpath.apply(
            lambda x: self._get_experiment_index(x)
        )
        self.actions = self.actions.merge(
            self.experiments.reset_index(), left_on="experiment_index", right_on="index"
        )

    def _get_experiment_index(self, action_local_path) -> int:
        """Return the ``experiments`` dataframe index of the action's parent experiment."""
        alp = os.path.dirname(os.path.dirname(action_local_path))
        return self.experiments.query(
            "experiment_localpath.str.startswith(@alp)"
        ).index[0]

    def clear_cache(self):
        """Drop the action/experiment/sequence/process yml caches."""
        self.act_cache = {}  # {uuid: json_dict}
        self.exp_cache = {}
        self.seq_cache = {}
        self.prc_cache = {}

    def get_yml(self, path: str) -> dict:
        """Load a YAML file from the indexed target (zip-aware).

        Args:
            path: Path of the yml file (relative inside a zip, absolute on disk).

        Returns:
            Parsed YAML dict.
        """
        if self.target.endswith(".zip") and not path.endswith("-prc.yml"):
            with ZipFile(self.target, "r") as zf:
                metad = dict(
                    yml_load(
                        zf.open(path).read().replace(b"\x89", b"%").decode("utf-8")
                    )
                )
        else:
            # metad = yml_load("".join(builtins.open(path, "r").readlines()))
            FM = FileMapper(path)
            metad = FM.read_yml(path)
        return metad

    def get_act(self, index=None, path: Optional[str] = None) -> "HelaoAction":
        """Load an action from the indexed target by dataframe ``index`` or yml ``path``.

        Args:
            index: Row index in ``self.actions``.
            path: Direct path to the action yml.

        Returns:
            ``HelaoAction`` wrapping the parsed yml.

        Raises:
            IndexError: If neither ``index`` nor ``path`` was supplied.
        """
        if index is None and path is None:
            raise IndexError("neither index, nor path arguments were supplied")
        if path is None:
            path = self.actions.iloc[index].action_localpath
        metad = self.act_cache.get(path, self.get_yml(path))
        self.act_cache[path] = metad
        return HelaoAction(path, metad, self)

    def get_exp(self, index=None, path: Optional[str] = None) -> "HelaoExperiment":
        """Load an experiment by dataframe ``index`` or yml ``path``.

        Args:
            index: Row index in ``self.experiments``.
            path: Direct path to the experiment yml.

        Returns:
            ``HelaoExperiment`` wrapping the parsed yml.

        Raises:
            IndexError: If neither ``index`` nor ``path`` was supplied.
        """
        if index is None and path is None:
            raise IndexError("neither index, nor path arguments were supplied")
        if path is None:
            path = self.experiments.iloc[index].experiment_localpath
        metad = self.exp_cache.get(path, self.get_yml(path))
        self.exp_cache[path] = metad
        return HelaoExperiment(path, metad, self)

    def get_seq(self, index=None, path: Optional[str] = None) -> "HelaoSequence":
        """Load a sequence by dataframe ``index`` or yml ``path``.

        Args:
            index: Row index in ``self.sequences``.
            path: Direct path to the sequence yml.

        Returns:
            ``HelaoSequence`` wrapping the parsed yml.

        Raises:
            IndexError: If neither ``index`` nor ``path`` was supplied.
        """
        if index is None and path is None:
            raise IndexError("neither index, nor path arguments were supplied")
        if path is None:
            path = self.sequences.iloc[index].sequence_localpath
        metad = self.seq_cache.get(path, self.get_yml(path))
        self.seq_cache[path] = metad
        return HelaoSequence(path, metad, self)

    def get_prc(self, index=None, path: Optional[str] = None) -> "HelaoProcess":
        """Load a process by dataframe ``index`` or yml ``path``.

        Args:
            index: Row index in ``self.processes``.
            path: Direct path to the process yml.

        Returns:
            ``HelaoProcess`` wrapping the parsed yml.

        Raises:
            IndexError: If neither ``index`` nor ``path`` was supplied.
        """
        if index is None and path is None:
            raise IndexError("neither index, nor path arguments were supplied")
        if path is None:
            path = self.processes.iloc[index].process_localpath
        metad = self.prc_cache.get(path, self.get_yml(path))
        self.prc_cache[path] = metad
        return HelaoProcess(path, metad, self)

    def get_hlo(self, yml_path: str, hlo_fn: str) -> tuple:
        """Read an HLO file as ``(meta_dict, data_dict)`` (zip-aware).

        For zip targets the YAML header and JSONL data section are parsed
        directly from the archive; otherwise ``FileMapper.read_hlo`` is used.

        Args:
            yml_path: Path of the owning ``-act.yml`` file.
            hlo_fn: HLO file name relative to ``yml_path``.

        Returns:
            ``(meta, data)`` where ``data`` aggregates JSONL values per key.
        """
        if self.target.endswith(".zip"):
            hlotarget = "/".join([os.path.dirname(yml_path), hlo_fn])
            with ZipFile(self.target, "r") as zf:
                content = zf.open(hlotarget).read()
            return read_hlo_bytes(content)
        else:
            # return read_hlo(os.path.join(os.path.dirname(yml_path), hlo_fn))
            FM = FileMapper(yml_path)
            hlo_path = os.path.join(os.path.dirname(yml_path), hlo_fn)
            return FM.read_hlo(hlo_path)

    def get_bytes(self, yml_path: str, fn: str) -> bytes:
        """Return raw bytes of ``fn`` (zip-aware) relative to ``yml_path``.

        Args:
            yml_path: Path of the owning yml file (``""`` for a top-level zip lookup).
            fn: Target file path.

        Returns:
            Raw file bytes.
        """
        if self.target.endswith(".zip") and yml_path == "":
            rel_seqzip_path = fn
            for seq_dir in sorted(
                self.sequences.sequence_dir, key=len, reverse=True
            ):
                if seq_dir and seq_dir in fn:
                    rel_seqzip_path = fn.split(seq_dir, 1)[-1].lstrip("/")
                    # MicroOrch zips are RUNS_FINISHED-rooted, so arcnames keep
                    # the seq_dir prefix; regular Orch sequence zips are rooted
                    # at the sequence, so the prefix is dropped.
                    if self._is_microorch_zip:
                        rel_seqzip_path = f"{seq_dir}/{rel_seqzip_path}".rstrip("/")
                    else:
                        rel_seqzip_path = rel_seqzip_path.rstrip("/")
                    break
            with ZipFile(self.target, "r") as zf:
                fbytes = zf.open(rel_seqzip_path).read()
        else:
            FM = FileMapper(yml_path)
            fpath = os.path.join(os.path.dirname(yml_path), fn)
            fbytes = FM.read_bytes(fpath)
        return fbytes

    def get_parquet(self, yml_path: str, par_fn: str) -> pd.DataFrame:
        """Read a parquet file (zip-aware) into a dataframe.

        Args:
            yml_path: Path of the owning yml file.
            par_fn: Parquet file name relative to ``yml_path``.

        Returns:
            Decoded parquet contents.
        """
        parbytes = self.get_bytes(yml_path, par_fn)
        return pd.read_parquet(BytesIO(parbytes))


ABBR_MAP = {"act": "action", "exp": "experiment", "seq": "sequence", "prc": "process"}


class HelaoModel:
    """Base wrapper around a yml record discovered by ``LocalLoader``.

    Hydrates ``name``/``uuid``/``timestamp``/``params`` from ``meta_dict``,
    keeping a reference to the originating loader so subclasses can resolve
    related files lazily.

    Attributes:
        name: Record name (technique name for processes).
        uuid: Record UUID.
        helao_type: One of ``action``/``experiment``/``sequence``/``process``.
        timestamp: Record timestamp.
        params: Record ``*_params`` dict.
        yml_path: Path the record was loaded from.
        meta_dict: Raw parsed yml dict.
        loader: ``LocalLoader`` that produced this object.
    """

    name: str
    uuid: UUID
    helao_type: str
    timestamp: datetime
    params: dict

    def __init__(self, yml_path: str, meta_dict: dict, loader: LocalLoader):
        """Populate the base attributes from ``meta_dict``.

        Args:
            yml_path: Path of the source yml file.
            meta_dict: Parsed yml contents.
            loader: ``LocalLoader`` reference for follow-up reads.
        """
        yml_type = yml_path.split("-")[-1].split(".")[0]
        helao_type = ABBR_MAP[yml_type]
        self.yml_path = yml_path
        self.helao_type = helao_type
        if helao_type != "process":
            self.name = meta_dict[f"{helao_type}_name"]
        else:
            self.name = meta_dict["technique_name"]
        self.uuid = meta_dict[f"{helao_type}_uuid"]
        self.timestamp = meta_dict[f"{helao_type}_timestamp"]
        self.params = meta_dict[f"{helao_type}_params"]
        self.meta_dict = meta_dict
        self._meta_dict = self.meta_dict  # alias for HelaoLoader parity
        self.loader = loader

    @property
    def json(self) -> dict:
        """Parsed yml dict (alias for ``self.meta_dict``)."""
        return self.meta_dict


class HelaoDataModel(HelaoDataModelMixin, HelaoModel):
    """``HelaoModel`` mixed with HLO-data accessors for action and process records."""

    @property
    def hlo(self) -> tuple:
        """``(meta, data)`` for the primary HLO file via the owning loader."""
        return self.loader.get_hlo(self.yml_path, self.hlo_file["file_name"])

    def read_hlo_file(self, filename) -> tuple:
        """Read an arbitrary HLO ``filename`` from this record's directory."""
        return self.loader.get_hlo(self.yml_path, filename)


class HelaoAction(HelaoDataModel):
    """Action record loaded from a local yml tree, with HLO accessors.

    Attributes:
        action_name: Action name.
        action_uuid: Action UUID.
        action_timestamp: Action timestamp.
        action_params: Action parameters dict.
    """

    action_name: str
    action_uuid: UUID
    action_timestamp: datetime
    action_params: dict

    def __init__(self, yml_path: str, meta_dict: dict, loader: LocalLoader):
        """Populate ``action_*`` attributes from the parsed yml.

        Args:
            yml_path: Source yml path.
            meta_dict: Parsed yml dict.
            loader: Owning ``LocalLoader``.
        """
        super().__init__(yml_path=yml_path, meta_dict=meta_dict, loader=loader)
        self.action_name = self.name
        self.action_uuid = self.uuid
        self.action_timestamp = self.timestamp
        self.action_params = self.params


class HelaoExperiment(HelaoModel):
    """Experiment record loaded from a local yml tree.

    Attributes:
        experiment_name: Experiment name.
        experiment_uuid: Experiment UUID.
        experiment_timestamp: Experiment timestamp.
        experiment_params: Experiment parameters dict.
    """

    experiment_name: str
    experiment_uuid: UUID
    experiment_timestamp: datetime
    experiment_params: dict

    def __init__(self, yml_path: str, meta_dict: dict, loader: LocalLoader):
        """Populate ``experiment_*`` attributes from the parsed yml.

        Args:
            yml_path: Source yml path.
            meta_dict: Parsed yml dict.
            loader: Owning ``LocalLoader``.
        """
        super().__init__(yml_path=yml_path, meta_dict=meta_dict, loader=loader)
        self.experiment_name = self.name
        self.experiment_uuid = self.uuid
        self.experiment_timestamp = self.timestamp
        self.experiment_params = self.params


class HelaoSequence(HelaoModel):
    """Sequence record loaded from a local yml tree.

    Attributes:
        sequence_name: Sequence name.
        sequence_label: Sequence label (when present in metadata).
        sequence_uuid: Sequence UUID.
        sequence_timestamp: Sequence timestamp.
        sequence_params: Sequence parameters dict.
    """

    sequence_name: str
    sequence_label: str
    sequence_uuid: UUID
    sequence_timestamp: datetime
    sequence_params: dict

    def __init__(self, yml_path: str, meta_dict: dict, loader: LocalLoader):
        """Populate ``sequence_*`` attributes from the parsed yml.

        Args:
            yml_path: Source yml path.
            meta_dict: Parsed yml dict.
            loader: Owning ``LocalLoader``.
        """
        super().__init__(yml_path=yml_path, meta_dict=meta_dict, loader=loader)
        self.sequence_name = self.name
        self.sequence_uuid = self.uuid
        self.sequence_timestamp = self.timestamp
        self.sequence_params = self.params
        self.sequence_label = meta_dict.get("sequence_label", "")


class HelaoProcess(HelaoModel):
    """Process record loaded from a local yml tree.

    Attributes:
        technique_name: Technique name from the source process.
        process_uuid: Process UUID.
        process_timestamp: Process timestamp.
        process_params: Process parameters dict.
    """

    technique_name: str
    process_uuid: UUID
    process_timestamp: datetime
    process_params: dict

    def __init__(self, yml_path: str, meta_dict: dict, loader: LocalLoader):
        """Populate ``process_*`` and ``technique_name`` attributes from the parsed yml.

        Args:
            yml_path: Source yml path.
            meta_dict: Parsed yml dict.
            loader: Owning ``LocalLoader``.
        """
        super().__init__(yml_path=yml_path, meta_dict=meta_dict, loader=loader)
        self.process_uuid = self.uuid
        self.process_timestamp = self.timestamp
        self.process_params = self.params
        self.technique_name = self.name

    @property
    def experiment(self) -> "HelaoExperiment":
        """Owning experiment, looked up via the loader's experiments frame."""
        exp_dir = os.path.basename(os.path.dirname(self.yml_path))
        exp_row = self.loader.experiments.query("experiment_dir==@exp_dir").index[0]
        return self.loader.get_exp(exp_row)

    @property
    def files(self) -> list:
        """``(rel_path, file_type, run_use)`` tuples for every contributing action file."""
        act_map = {
            ad["action_uuid"]: ad["action_output_dir"]
            for ad in self.json.get("dispatched_actions_abbr", [])
        }
        return [
            (
                f"{act_map[fd['action_uuid']]}/{fd['file_name']}",
                fd["file_type"],
                fd["run_use"],
            )
            for fd in self.json.get("files", [])
        ]

    def read_action_file(self, relative_path: str) -> bytes:
        """Read the raw bytes of an action file by its run-tree-relative path.

        Process yml files live in the ``PROCESSES`` tree, not beside the
        action files they reference, so the file is resolved against the run
        tree rather than relative to ``self.yml_path``. ``relative_path`` (as
        produced by :attr:`files`) is rooted at the ``RUNS_<state>`` directory
        — ``YY.WW/MMDD/<seq_dir>/<exp>/<act>/<file>`` — which is enough for
        :class:`FileMapper` to deduce and read from the owning synced sequence
        zip (``RUNS_SYNCED/YY.WW/MMDD/<seq_dir>.zip``) once the loose file is
        gone. Only the run root is taken from ``self.yml_path``.

        Args:
            relative_path: Action file path relative to the ``RUNS_<state>``
                root.

        Returns:
            Raw file bytes.
        """
        fm = FileMapper(self.yml_path)
        return fm.read_bytes(relative_path)

