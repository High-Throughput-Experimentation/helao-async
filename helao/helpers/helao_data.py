"""Browse and read sequence/experiment/action output trees produced by HELAO.

``HelaoData`` wraps either a directory tree under ``RUNS_*`` or a zipped
sequence and exposes its YAML metadata plus children (sub-sequences,
experiments, actions) and helpers for reading associated ``.hlo``,
``.parquet`` and ``.json`` data files.
"""

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER
from typing import Tuple
from collections import defaultdict

import os
import builtins
from glob import glob
from tempfile import TemporaryDirectory
import zipfile
import re

import orjson
import pandas as pd
from .yml_tools import yml_load
from .hlo_data import read_hlo
from .file_mapper import FileMapper


class HelaoData:
    """Navigate a sequence/experiment/action output tree or zipped sequence.

    A ``HelaoData`` is rooted at a ``-seq.yml``, ``-exp.yml`` or ``-act.yml``
    file (or a zip archive containing one) and recursively wraps its children
    as further ``HelaoData`` instances. It also lazily exposes the YAML
    metadata and a list of associated data files so callers can read .hlo,
    .parquet and .json payloads on demand.

    Attributes:
        ord: Short codes for the three levels (``seq``, ``exp``, ``act``).
        abbrd: Mapping from short codes to full names.
        target: Path to the directory, yml file, or zip archive.
        zflist: List of paths inside the zip archive (zip-mode only).
        ymlpath: Path of the YAML file describing this node.
        ymldir: Directory containing ``ymlpath``.
        type: One of ``seq``, ``exp`` or ``act`` for this node.
        seq: Child sequence nodes.
        exp: Child experiment nodes.
        act: Child action nodes.
        children: Flat concatenation of ``seq + exp + act``.
    """

    def __init__(self, target: str, **kwargs):
        """Build a ``HelaoData`` rooted at ``target``.

        Args:
            target: Either a path to a zip archive, a run directory, or a
                ``*-seq.yml`` / ``*-exp.yml`` / ``*-act.yml`` file. When a
                ``HelaoData`` instance is passed, its attributes are copied
                onto this instance.
            **zflist: Pre-computed list of zip member names (zip-mode only).
            **ztarget: Path inside the zip archive of the YAML to wrap.
        """
        self._yml_cache = {}
        self.ord = ["seq", "exp", "act"]
        self.abbrd = {"seq": "sequence", "exp": "experiment", "act": "action"}
        skip_exts = ["yml", "prg"]
        if isinstance(target, str):
            self.target = target
            if self.target.endswith(".zip"):  # this will always be a zipped sequence
                with zipfile.ZipFile(target, "r") as zf:
                    if "zflist" in kwargs:
                        self.zflist = kwargs["zflist"]
                    else:
                        self.zflist = [p for p in zf.namelist() if not p.endswith("/")]
                    if "ztarget" in kwargs:
                        self.ymlpath = kwargs["ztarget"]
                    else:
                        self.ymlpath = [
                            p for p in self.zflist if p.endswith("-seq.yml")
                        ][0]
                    self.ymldir = os.path.dirname(self.ymlpath)
                    self.type = self.ymlpath.split("-")[-1].replace(".yml", "")
                    # self.yml = yml_load(zf.open(self.ymlpath).read().decode("UTF-8"))
                self.seq = []
                self.exp = []
                self.act = []
                if self.type == "seq":
                    sub_exps = [
                        p
                        for p in self.zflist
                        if p.endswith("-exp.yml") and p.startswith(self.ymldir)
                    ]
                    self.exp = [
                        HelaoData(self.target, zflist=self.zflist, ztarget=p)
                        for p in sorted(
                            sub_exps,
                            key=lambda x: float(
                                os.path.basename(os.path.dirname(x)).split("__")[0]
                            ),
                        )
                    ]
                elif self.type == "exp":
                    sub_acts = [
                        p
                        for p in self.zflist
                        if p.endswith("-act.yml") and p.startswith(self.ymldir)
                    ]
                    self.act = [
                        HelaoData(self.target, zflist=self.zflist, ztarget=p)
                        for p in sorted(
                            sub_acts,
                            key=lambda x: float(
                                os.path.basename(os.path.dirname(x)).split("__")[0]
                            ),
                        )
                    ]
                self._data_files = [
                    p
                    for p in self.zflist
                    if p.split(".")[-1] not in skip_exts and p.startswith(self.ymldir)
                    # and os.path.dirname(p) == self.ymldir
                ]
                nosync_path = os.path.dirname(self.target).replace(
                    "RUNS_SYNCED", "RUNS_NOSYNC"
                )
            else:
                if os.path.isdir(self.target):
                    self.ymldir = self.target
                    self.ymlpath = glob(os.path.join(self.target, "*.yml"))[0]
                elif target.endswith(".yml"):
                    self.ymldir = os.path.dirname(self.target)
                    self.ymlpath = target
                self.type = self.ymlpath.split("-")[-1].replace(".yml", "")
                # self.yml = yml_load("".join(builtins.open(self.ymlpath, "r").readlines()))
                runstate = re.findall("RUNS_[A-Z]+", self.ymldir)[0]
                yml_reldir = self.ymldir.replace(runstate, "RUNS_*")
                self.seq = [
                    HelaoData(x)
                    for x in sorted(
                        glob(os.path.join(yml_reldir, "*", "*-seq.yml")),
                        key=lambda x: float(
                            os.path.basename(os.path.dirname(x)).split("__")[0]
                        ),
                    )
                ]
                self.exp = [
                    HelaoData(x)
                    for x in sorted(
                        glob(os.path.join(yml_reldir, "*", "*-exp.yml")),
                        key=lambda x: float(
                            os.path.basename(os.path.dirname(x)).split("__")[0]
                        ),
                    )
                ]
                self.act = [
                    HelaoData(x)
                    for x in sorted(
                        glob(os.path.join(yml_reldir, "*", "*-act.yml")),
                        key=lambda x: float(
                            os.path.basename(os.path.dirname(x)).split("__")[0]
                        ),
                    )
                ]
                self._data_files = [
                    x
                    for x in glob(os.path.join(yml_reldir, "**", "*"), recursive=True)
                    if x.split(".")[-1] not in skip_exts
                ]
                nosync_path = self.ymldir.replace("RUNS_SYNCED", "RUNS_NOSYNC")

            if os.path.exists(nosync_path):
                self._nosync_files = [p for p in self._data_files if "RUNS_NOSYNC" in p]

            self.children = self.seq + self.exp + self.act
        else:
            for k, v in vars(target).items():
                setattr(self, k, v)

    @property
    def yml(self) -> dict:
        """Return the parsed YAML metadata for this node (cached)."""
        if self._yml_cache:
            return self._yml_cache
        if self.target.endswith(".zip"):  # this will always be a zipped sequence
            with zipfile.ZipFile(self.target, "r") as zf:
                yml_dict = yml_load(zf.open(self.ymlpath).read().decode("UTF-8"))
        else:
            yml_dict = yml_load("".join(builtins.open(self.ymlpath, "r").readlines()))
        self._yml_cache = yml_dict
        return yml_dict

    @property
    def name(self) -> str:
        """Return the sequence/experiment/action name from the YAML."""
        return self.yml.get(f"{self.abbrd[self.type]}_name", "NA")

    @property
    def params(self) -> dict:
        """Return the parameter dictionary from the YAML, or ``{}``."""
        return self.yml.get(f"{self.abbrd[self.type]}_params", {})

    @property
    def uuid(self) -> str:
        """Return the UUID for this node from the YAML."""
        return self.yml[f"{self.abbrd[self.type]}_uuid"]

    @property
    def timestamp(self) -> str:
        """Return the timestamp for this node from the YAML."""
        return self.yml[f"{self.abbrd[self.type]}_timestamp"]

    @property
    def samples_in(self) -> list:
        """Return the ``samples_in`` list from the YAML, or ``[]``."""
        return self.yml.get("samples_in", [])

    @property
    def data_files(self) -> list:
        """Return paths of associated data files (excluding ``RUNS_NOSYNC``)."""
        if self.target.endswith(".zip"):
            return self._data_files
        return [
            str(FileMapper(p).locate(p))
            for p in self._data_files
            if "RUNS_NOSYNC" not in p
        ]

    @property
    def nosync_files(self) -> list:
        """Return paths of data files that live under ``RUNS_NOSYNC``."""
        if self.target.endswith(".zip"):
            return self._nosync_files
        return [
            str(FileMapper(p).locate(p)) for p in self._data_files if "RUNS_NOSYNC" in p
        ]

    @property
    def ls(self):
        """Print this node and its children with their indices."""
        return print(
            "\n".join(
                [self.__repr__()]
                + [f"  [{i}] " + x.__repr__() for i, x in enumerate(self.children)]
            )
        )

    def read_hlo(
        self, hlotarget: str, keep_keys: list = [], omit_keys: list = []
    ) -> Tuple[dict, dict]:
        """Read a ``.hlo`` file and return its YAML header and data dict.

        When this ``HelaoData`` wraps a zip archive (and ``hlotarget`` is not a
        ``RUNS_NOSYNC`` path), reads the member from inside the archive;
        otherwise delegates to ``read_hlo`` for an on-disk path.

        Args:
            hlotarget: Path of the ``.hlo`` file (relative inside the zip when
                the archive is the target).
            keep_keys: When non-empty, only these data keys are kept.
            omit_keys: Data keys to discard (applied when ``keep_keys`` is empty).

        Returns:
            A ``(meta, data)`` tuple where ``meta`` is the parsed YAML header
            and ``data`` is a dict of column lists.
        """
        if self.target.endswith(".zip") and "RUNS_NOSYNC" not in hlotarget:
            header_lines = []
            header_end = False
            data = defaultdict(list)

            with zipfile.ZipFile(self.target, "r") as zf:
                for line in zf.open(hlotarget):
                    if header_end:
                        line_dict = orjson.loads(line)
                        for k in line_dict:
                            if k in keep_keys or k not in omit_keys:
                                v = line_dict[k]
                                if isinstance(v, list):
                                    data[k] += v
                                else:
                                    data[k].append(v)
                    elif line.decode("utf8").startswith("%%"):
                        header_end = True
                    elif not header_end:
                        header_lines.append(line)
            if header_lines:
                meta = dict(yml_load("".join([x.decode("utf8") for x in header_lines])))
            else:
                meta = {}
            return meta, data
        else:
            return read_hlo(hlotarget)

    def read_parquet(
        self, hlotarget: str, keep_keys: list = [], omit_keys: list = []
    ) -> Tuple[dict, pd.DataFrame]:
        """Read a Parquet file and return ``({}, column_dict)``.

        Args:
            hlotarget: Path of the Parquet file (relative inside the zip when
                the archive is the target).
            keep_keys: Unused; accepted for API symmetry with ``read_hlo``.
            omit_keys: Unused; accepted for API symmetry with ``read_hlo``.

        Returns:
            A tuple of an empty metadata dict and a dict-of-lists view of the
            Parquet contents.
        """
        if self.target.endswith(".zip") and "RUNS_NOSYNC" not in hlotarget:
            with TemporaryDirectory() as tmpdir:
                with zipfile.ZipFile(self.target, "r") as zf:
                    parquet_path = zf.extract(hlotarget, tmpdir)
                    parquet_df = pd.read_parquet(parquet_path)
        else:
            parquet_df = pd.read_parquet(hlotarget)

        return {}, parquet_df.to_dict(orient="list")

    def read_json(
        self, hlotarget: str, keep_keys: list = [], omit_keys: list = []
    ) -> Tuple[dict, dict]:
        """Read a JSON data file and return ``({}, parsed_dict)``.

        Args:
            hlotarget: Path of the JSON file (relative inside the zip when
                the archive is the target).
            keep_keys: Unused; accepted for API symmetry with ``read_hlo``.
            omit_keys: Unused; accepted for API symmetry with ``read_hlo``.

        Returns:
            A tuple of an empty metadata dict and the parsed JSON object.
        """
        if self.target.endswith(".zip") and "RUNS_NOSYNC" not in hlotarget:
            json_dict = orjson.loads(self.read_file(hlotarget))
        else:
            with open(hlotarget, "rb") as f:
                json_dict = orjson.loads(f.read())

        return {}, json_dict

    def read_file(self, hlotarget) -> bytes:
        """Read a single zip member as raw bytes.

        Args:
            hlotarget: Path of the member inside the zip archive.

        Returns:
            The member's contents as bytes.
        """
        bytes = zipfile.Path(self.target, hlotarget).read_bytes()
        return bytes

    def read_data_file(self, target_data_file: str) -> Tuple[dict, dict]:
        """Dispatch to the reader matching the file extension.

        Args:
            target_data_file: Path of the data file to read.

        Returns:
            A ``(meta, data)`` tuple, or ``({}, {})`` if the extension is not
            supported.
        """
        if target_data_file.endswith(".hlo"):
            return self.read_hlo(target_data_file)
        elif target_data_file.endswith(".json"):
            return self.read_json(target_data_file)
        elif target_data_file.endswith(".parquet"):
            return self.read_parquet(target_data_file)
        else:
            LOGGER.warn("File not found or type unsupported.")
            return {}, {}

    def read_data_index(self, idx: int = 0):
        """Read the ``idx``-th data file, falling back to nosync files.

        Args:
            idx: Index into ``data_files`` (or ``nosync_files`` when the
                former is empty).

        Returns:
            A ``(meta, data)`` tuple, or ``({}, {})`` if no data file is
            available.
        """
        try:
            if self.data_files:
                target_data_file = self.data_files[idx]
            elif self.nosync_files:
                target_data_file = self.nosync_files[idx]
            else:
                return {}, {}
            return self.read_data_file(target_data_file)
        except Exception:
            LOGGER.error("Error reading data.", exc_info=True)

    @property
    def data(self):
        """Return the ``(meta, data)`` tuple from the first data file."""
        return self.read_data_index(0)

    def __repr__(self) -> str:
        """Return a one-line summary of the node type, name and timestamp."""
        return f"{self.abbrd[self.type]}: {self.name} @ {self.timestamp} CONTAINING {len(self.children)} children"
