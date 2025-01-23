"""
This module provides functionality to read and manage Helao data files, specifically .hlo files and YAML files. It includes the following:
Functions:
    read_hlo(path: str) -> Tuple[dict, dict]:
Classes:
    HelaoData:
            __init__(self, target: str, **kwargs):
            ls:
            read_hlo(self, hlotarget):
            read_file(self, hlotarget):
            data:
            __repr__(self):
                Returns a string representation of the object.
"""

__all__ = ["read_hlo", "HelaoData"]

import os
import orjson
import builtins
from pathlib import Path
from typing import Tuple
from collections import defaultdict
from glob import glob
from zipfile import ZipFile
import zipfile
from tqdm import tqdm
import re

from helao.helpers.yml_tools import yml_load


def read_hlo(
    path: str, keep_keys: list = [], omit_keys: list = []
) -> Tuple[dict, dict]:
    """
    Reads a .hlo file and returns its metadata and data.
    Args:
        path (str): The file path to the .hlo file.
    Returns:
        Tuple[dict, dict]: A tuple containing two dictionaries:
            - The first dictionary contains the metadata.
            - The second dictionary contains the data, where each key maps to a list of values.
    """
    if keep_keys and omit_keys:
        print(
            "Both keep_keys and omit_keys are provided. keep_keys will take precedence."
        )

    path_to_hlo = Path(path)
    header_lines = []
    header_end = False
    data = defaultdict(list)

    with open(str(path_to_hlo), "rb") as f:
        for line in f:
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


class HelaoData:
    """
    A class to represent and manage Helao data, which can be stored in either a directory or a zip file.

    Attributes:
        ord (list): Order of data types.
        abbrd (dict): Abbreviations for data types.
        target (str): Path to the target file or directory.
        zflist (list): List of files in the zip archive.
        ymlpath (str): Path to the YAML file.
        ymldir (str): Directory containing the YAML file.
        type (str): Type of the data (sequence, experiment, or action).
        yml (dict): Parsed YAML content.
        seq (list): List of sequence data.
        exp (list): List of experiment data.
        act (list): List of action data.
        data_files (list): List of data files.
        name (str): Name of the data.
        params (dict): Parameters of the data.
        uuid (str): UUID of the data.
        timestamp (str): Timestamp of the data.
        samples_in (list): List of input samples.
        children (list): List of child data objects.

    Methods:
        ls: Prints a list of child data objects.
        read_hlo(hlotarget): Reads HLO data from the target.
        read_file(hlotarget): Reads a file from the zip archive.
        data: Returns the data from the first data file.
        __repr__(): Returns a string representation of the object.
    """

    def __init__(self, target: str, **kwargs):
        """
        Initialize a HelaoData object.

        Parameters:
        target (str): The target file or directory. This can be a path to a zip file,
                      a directory, or a YAML file.
        **kwargs: Additional keyword arguments.
            - zflist (list): List of files in the zip archive.
            - ztarget (str): Target YAML file within the zip archive.

        Attributes:
        ord (list): List of strings representing the order of data types.
        abbrd (dict): Dictionary mapping abbreviations to full names.
        target (str): The target file or directory.
        zflist (list): List of files in the zip archive.
        ymlpath (str): Path to the YAML file.
        ymldir (str): Directory containing the YAML file.
        type (str): Type of the YAML file (sequence, experiment, or action).
        yml (dict): Parsed YAML content.
        seq (list): List of HelaoData objects for sequences.
        exp (list): List of HelaoData objects for experiments.
        act (list): List of HelaoData objects for actions.
        data_files (list): List of data files.
        name (str): Name of the sequence, experiment, or action.
        params (dict): Parameters of the sequence, experiment, or action.
        uuid (str): UUID of the sequence, experiment, or action.
        timestamp (str): Timestamp of the sequence, experiment, or action.
        samples_in (list): List of input samples.
        children (list): List of child HelaoData objects (sequences, experiments, actions).
        """
        self.ord = ["seq", "exp", "act"]
        self.abbrd = {"seq": "sequence", "exp": "experiment", "act": "action"}
        self.target = target
        if self.target.endswith(".zip"):  # this will always be a zipped sequence
            with ZipFile(target, "r") as zf:
                if "zflist" in kwargs:
                    self.zflist = kwargs["zflist"]
                else:
                    self.zflist = [p for p in zf.namelist() if not p.endswith("/")]
                if "ztarget" in kwargs:
                    self.ymlpath = kwargs["ztarget"]
                else:
                    self.ymlpath = [p for p in self.zflist if p.endswith("-seq.yml")][0]
                self.ymldir = os.path.dirname(self.ymlpath)
                self.type = self.ymlpath.split("-")[-1].replace(".yml", "")
                self.yml = yml_load(zf.open(self.ymlpath).read().decode("UTF-8"))
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
            self.data_files = [
                p
                for p in self.zflist
                if p.endswith(".hlo")
                and p.startswith(self.ymldir)
                and os.path.dirname(p) == self.ymldir
            ]
            nosync_path = os.path.dirname(self.target).replace("RUNS_SYNCED", "RUNS_NOSYNC")
        else:
            if os.path.isdir(self.target):
                self.ymldir = self.target
                self.ymlpath = glob(os.path.join(self.target, "*.yml"))[0]
            elif target.endswith(".yml"):
                self.ymldir = os.path.dirname(self.target)
                self.ymlpath = target
            self.type = self.ymlpath.split("-")[-1].replace(".yml", "")
            self.yml = yml_load("".join(builtins.open(self.ymlpath, "r").readlines()))
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
            self.data_files = glob(os.path.join(yml_reldir, "*.hlo"))
            nosync_path = self.ymldir.replace("RUNS_SYNCED", "RUNS_NOSYNC")

        if os.path.exists(nosync_path):
            self.nosync_files = [p for p in self.data_files if "RUNS_NOSYNC" in p]
            self.data_files = [p for p in self.data_files if "RUNS_NOSYNC" not in p]

        self.name = self.yml.get(f"{self.abbrd[self.type]}_name", "NA")
        self.params = self.yml.get(f"{self.abbrd[self.type]}_params", {})
        self.uuid = self.yml[f"{self.abbrd[self.type]}_uuid"]
        self.timestamp = self.yml[f"{self.abbrd[self.type]}_timestamp"]
        self.samples_in = self.yml.get("samples_in", [])
        self.children = self.seq + self.exp + self.act

    @property
    def ls(self):
        """
        Prints a formatted string representation of the current object and its children.

        The method prints the string representation of the current object followed by
        the string representations of its children, each prefixed with their index in
        the list of children.

        Returns:
            None
        """
        return print(
            "\n".join(
                [self.__repr__()]
                + [f"  [{i}] " + x.__repr__() for i, x in enumerate(self.children)]
            )
        )

    def read_hlo(
        self, hlotarget: str, keep_keys: list = [], omit_keys: list = []
    ) -> Tuple[dict, dict]:
        """
        Reads and processes a .hlo file from a zip archive or directly.

        If the target file ends with ".zip", it reads the specified hlotarget file
        from within the zip archive, decodes the lines, and processes the metadata
        and data sections. The metadata is parsed as YAML, and the data is parsed
        as JSON and stored in a defaultdict.

        Args:
            hlotarget (str): The target .hlo file to read.

        Returns:
            tuple: A tuple containing:
            - meta (dict): The metadata parsed from the .hlo file.
            - data (defaultdict): The data parsed from the .hlo file, organized
              into a defaultdict of lists.
        """
        if self.target.endswith(".zip") and "RUNS_NOSYNC" not in hlotarget:
            header_lines = []
            header_end = False
            data = defaultdict(list)

            with ZipFile(self.target, "r") as zf:
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

    def read_file(self, hlotarget):
        """
        Reads the contents of a file within a zip archive.

        Args:
            hlotarget (str): The path to the target file within the zip archive.

        Returns:
            bytes: The contents of the file as bytes.
        """
        bytes = zipfile.Path(self.target, hlotarget).read_bytes()
        return bytes

    @property
    def data(self):
        """
        Reads the first data file in the `data_files` list using the `read_hlo` method.

        Returns:
            The data read from the first file in the `data_files` list.
        """
        if self.data_files:
            return self.read_hlo(self.data_files[0])
        elif self.nosync_files:
            return self.read_hlo(self.nosync_files[0])
        else:
            return {}, {}

    def __repr__(self):
        return f"{self.abbrd[self.type]}: {self.name} @ {self.timestamp} CONTAINING {len(self.children)} children"
