"""
sync_driver.py

This module provides classes and functions for synchronizing Helao YAML files with S3 and an API.
It includes functionality for converting dictionaries to JSON, moving files between directories,
and handling synchronization progress.

Classes:
    HelaoYml: Represents a Helao YAML file and provides methods for managing its state and metadata.
    Progress: Manages the synchronization progress of a Helao YAML file.
    HelaoSyncer: Handles the synchronization of Helao YAML files with S3 and an API.

Functions:
    dict2json(input_dict: dict): Converts a dictionary to a file-like object containing JSON.
    move_to_synced(file_path: Path): Moves a file from the RUNS_FINISHED directory to the RUNS_SYNCED directory.
    revert_to_finished(file_path: Path): Moves a file from the RUNS_SYNCED directory to the RUNS_FINISHED directory.
"""

__all__ = ["HelaoYml", "Progress", "HelaoSyncer"]

import os
import shutil
import io
import codecs
import json
import asyncio
from zipfile import ZipFile
from pathlib import Path
from datetime import datetime
from typing import Union, Optional, Dict, List
import traceback
from collections import defaultdict
from copy import copy

import botocore.exceptions
import boto3
import gzip

# from filelock import FileLock

from helao.helpers import logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

from helao.servers.base import Base
from helao.core.models.process import ProcessModel
from helao.core.models.action import ShortActionModel, ActionModel
from helao.core.models.experiment import ExperimentModel
from helao.core.models.sequence import SequenceModel
from helao.core.models.file import FileInfo
from helao.helpers.gen_uuid import gen_uuid
from helao.helpers.read_hlo import read_hlo
from helao.helpers.parquet import hlo_to_parquet
from helao.helpers.yml_tools import yml_dumps, yml_load
from helao.helpers.zip_dir import zip_dir

from time import sleep
from glob import glob
import aiohttp

ABR_MAP = {"act": "action", "exp": "experiment", "seq": "sequence"}
MOD_MAP = {
    "action": ActionModel,
    "experiment": ExperimentModel,
    "sequence": SequenceModel,
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


def dict2json(input_dict: dict):
    """
    Converts a dictionary to a JSON byte stream.

    Args:
        input_dict (dict): The dictionary to convert to JSON.

    Returns:
        io.BytesIO: A byte stream containing the JSON representation of the input dictionary.
    """
    bio = io.BytesIO()
    stream_writer = codecs.getwriter("utf-8")
    wrapper_file = stream_writer(bio)
    json.dump(input_dict, wrapper_file)
    bio.seek(0)
    return bio


def move_to_synced(file_path: Path):
    """
    Moves a file from the "RUNS_FINISHED" directory to the "RUNS_SYNCED" directory.

    Args:
        file_path (Path): The path of the file to be moved.

    Returns:
        Path: The new path of the file if the move was successful.
        bool: False if there was a PermissionError during the move.
    """
    parts = list(file_path.parts)
    state_index = parts.index("RUNS_FINISHED")
    parts[state_index] = "RUNS_SYNCED"
    target_path = Path(*parts)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        new_path = file_path.replace(target_path)
        return new_path
    except PermissionError:
        print(f"Permission error when moving {file_path} to {target_path}")
        return False


def revert_to_finished(file_path: Path):
    """
    Reverts the state of a file path from "RUNS_SYNCED" to "RUNS_FINISHED".

    This function takes a file path, changes the directory name from "RUNS_SYNCED"
    to "RUNS_FINISHED", creates the necessary directories if they do not exist,
    and moves the file to the new path.

    Args:
        file_path (Path): The original file path with "RUNS_SYNCED" in its parts.

    Returns:
        Path: The new file path with "RUNS_FINISHED" if the operation is successful.
        bool: False if there is a PermissionError during the file move operation.

    Raises:
        ValueError: If "RUNS_SYNCED" is not found in the file path parts.
    """
    parts = list(file_path.parts)
    state_index = parts.index("RUNS_SYNCED")
    parts[state_index] = "RUNS_FINISHED"
    target_path = Path(*parts)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        new_path = file_path.replace(target_path)
        return new_path
    except PermissionError:
        print(f"Permission error when moving {file_path} to {target_path}")
        return False


class HelaoYml:
    """
    HelaoYml is a class that handles YAML file operations for Helao directories.

    Attributes:
        target (Path): The target YAML file path.
        targetdir (Path): The directory containing the target YAML file.

    Methods:
        __init__(self, target: Union[Path, str]):
            Initializes the HelaoYml object with the given target path.

        parts(self):
            Returns the parts of the target path as a list.

        check_paths(self):
            Checks if the target path exists and updates the target path if necessary.

        exists(self):
            Checks if the target path exists.

        __repr__(self):
            Returns a string representation of the HelaoYml object.

        type(self):
            Returns the type of the YAML file based on its stem.

        timestamp(self):
            Returns the timestamp of the YAML file based on its stem.

        status(self):
            Returns the status of the YAML file based on its directory.

        rename(self, status: str) -> str:
            Renames the target path with the given status.

        status_idx(self):
            Returns the index of the status in the parts of the target path.

        relative_path(self):
            Returns the relative path of the target path.

        active_path(self):
            Returns the active path of the target path.

        finished_path(self):
            Returns the finished path of the target path.

        synced_path(self):
            Returns the synced path of the target path.

        cleanup(self):
            Removes empty directories in RUNS_ACTIVE or RUNS_FINISHED.

        list_children(self, yml_path: Path):
            Lists the children YAML files in the given path.

        active_children(self) -> list:
            Returns the active children YAML files.

        finished_children(self) -> list:
            Returns the finished children YAML files.

        synced_children(self) -> list:
            Returns the synced children YAML files.

        children(self) -> list:
            Returns all children YAML files sorted by timestamp.

        misc_files(self) -> List[Path]:
            Returns a list of miscellaneous files in the target directory.

        lock_files(self) -> List[Path]:
            Returns a list of lock files in the target directory.

        hlo_files(self) -> List[Path]:
            Returns a list of HLO files in the target directory.

        parent_path(self) -> Path:
            Returns the parent path of the target YAML file.

        write_meta(self, meta_dict: dict):
            Writes the given metadata dictionary to the target YAML file.
    """

    target: Path
    targetdir: Path

    def __init__(self, target: Union[Path, str]):
        """
        Initialize the SyncDriver with a target path.

        Args:
            target (Union[Path, str]): The target path for the SyncDriver. It can be either a Path object or a string.

        Raises:
            TypeError: If the target is neither a Path object nor a string.
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
    def parts(self):
        """
        Returns a list of parts from the target.

        Returns:
            list: A list containing the parts of the target.
        """
        return list(self.target.parts)

    def check_paths(self):
        """
        Checks and validates the paths for the Helao directory structure.

        This method performs the following checks:
        1. If the `self.exists` attribute is False, it iterates through the paths
           (`self.active_path`, `self.finished_path`, `self.synced_path`) to find
           an existing path and sets `self.target` to the first existing path found.
           If no existing path is found, it prints an error message.
        2. If `self.target` is a directory, it sets `self.targetdir` to `self.target`
           and searches for `.yml` files with specific suffixes (`-seq`, `-exp`, `-act`).
           If multiple or no such `.yml` files are found, it raises a `ValueError`.
           Otherwise, it sets `self.target` to the found `.yml` file.
        3. If `self.target` is not a directory, it sets `self.targetdir` to the parent
           directory of `self.target`.
        4. It checks if any part of `self.targetdir` starts with "RUNS_". If not, it
           raises a `ValueError`.

        Raises:
            ValueError: If multiple or no valid `.yml` files are found in the target
                        directory, or if the target is not located within a Helao
                        RUNS_* directory.
        """
        if not self.exists:
            for p in (self.active_path, self.finished_path, self.synced_path):
                self.target = p
                if self.exists:
                    break
            if not self.exists:
                print(f"{self.target} does not exist")
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
    def exists(self):
        """
        Check if the target exists.

        Returns:
            bool: True if the target exists, False otherwise.
        """
        return self.target.exists()

    def __repr__(self):
        """
        Return a string representation of the object.

        The representation includes the first three characters of the type in uppercase,
        the name of the parent of the target, and the status of the object.

        Returns:
            str: A string representation of the object.
        """
        return f"{self.type[:3].upper()}: {self.target.parent.name} ({self.status})"

    @property
    def type(self):
        """
        Determines the type of the target based on its stem.

        The method extracts the last part of the target's stem (separated by a dash)
        and uses it to look up the corresponding type in the ABR_MAP dictionary.

        Returns:
            The type of the target as defined in the ABR_MAP dictionary.
        """
        return ABR_MAP[self.target.stem.split("-")[-1]]

    @property
    def timestamp(self):
        """
        Extracts and returns a timestamp from the filename of the target file.

        The filename is expected to have a format where the timestamp is the first part,
        separated by a hyphen, and follows the format "%Y%m%d.%H%M%S%f".

        Returns:
            datetime: A datetime object representing the extracted timestamp.
        """
        ts = datetime.strptime(self.target.stem.split("-")[0], "%Y%m%d.%H%M%S%f")
        return ts

    @property
    def status(self):
        """
        Determine the status of the target directory.

        This method extracts the status from the target directory path. It looks for
        a directory part that starts with "RUNS_" and then splits this part to get
        the status, which is converted to lowercase.

        Returns:
            str: The status extracted from the target directory path.
        """
        path_parts = [x for x in self.targetdir.parts if x.startswith("RUNS_")]
        status = path_parts[0].split("_")[-1].lower()
        return status

    def rename(self, status: str) -> str:
        """
        Renames a part of the file path with the given status.

        Args:
            status (str): The new status to replace in the file path.

        Returns:
            str: The new file path with the updated status.
        """
        tempparts = list(self.parts)
        tempparts[self.status_idx] = status
        return os.path.join(*tempparts)

    @property
    def status_idx(self):
        """
        Determine the index of the first element in `self.parts` that matches any of the valid statuses.

        The method checks each element in `self.parts` to see if it matches any of the statuses in
        `valid_statuses` ("RUNS_ACTIVE", "RUNS_FINISHED", "RUNS_SYNCED"). It returns the index of the
        first matching element.

        Returns:
            int: The index of the first element in `self.parts` that matches any of the valid statuses.

        Raises:
            ValueError: If no element in `self.parts` matches any of the valid statuses.
        """
        valid_statuses = ("RUNS_ACTIVE", "RUNS_FINISHED", "RUNS_SYNCED")
        return [any([x in valid_statuses]) for x in self.parts].index(True)

    @property
    def relative_path(self):
        """
        Generate a relative path by joining parts of the path starting from the status index + 1.

        Returns:
            str: The relative path as a string.
        """
        return "/".join(list(self.parts)[self.status_idx + 1 :])

    @property
    def active_path(self):
        """
        Returns the active path for the current run.

        This method constructs and returns a Path object representing the
        directory for active runs. It uses the `rename` method to generate
        the directory name "RUNS_ACTIVE".

        Returns:
            Path: A Path object pointing to the "RUNS_ACTIVE" directory.
        """
        return Path(self.rename("RUNS_ACTIVE"))

    @property
    def finished_path(self):
        """
        Generates a finished path by renaming the current path to "RUNS_FINISHED".

        Returns:
            Path: The new path with the name "RUNS_FINISHED".
        """
        return Path(self.rename("RUNS_FINISHED"))

    @property
    def synced_path(self):
        """
        Generates a synchronized path by renaming the current path to "RUNS_SYNCED".

        Returns:
            Path: A Path object representing the synchronized path.
        """
        return Path(self.rename("RUNS_SYNCED"))

    def cleanup(self):
        """
        Cleans up the target directory by removing empty directories.

        This method checks if the target directory exists and is not the same as the
        synced path. If the target directory does not exist or is the same as the
        synced path, it returns "success". Otherwise, it iterates through the parts
        of the directory path and attempts to remove empty directories.

        Returns:
            str: "success" if cleanup is successful or if the target directory does
                 not exist or is the same as the synced path. "failed" if a directory
                 is not empty. A string representation of the error if a PermissionError
                 occurs during directory removal.
        """
        if not self.target.exists() or self.target == self.synced_path:
            return "success"
        tempparts = list(self.parts)
        steps = len(tempparts) - self.status_idx
        for i in range(1, steps):
            check_dir = Path(os.path.join(*tempparts[:-i]))
            contents = [x for x in check_dir.glob("*") if x != check_dir]
            if contents:
                print(f"{str(check_dir)} is not empty")
                print(contents)
                return "failed"
            try:
                check_dir.rmdir()
            except PermissionError as err:
                str_err = "".join(
                    traceback.format_exception(type(err), err, err.__traceback__)
                )
                return str_err
        return "success"

    def list_children(self, yml_path: Path):
        """
        List and sort child YAML files by timestamp.

        Args:
            yml_path (Path): The path to the parent directory containing YAML files.

        Returns:
            List[HelaoYml]: A sorted list of HelaoYml objects based on their timestamp.
        """
        paths = yml_path.parent.glob("*/*.yml")
        hpaths = [HelaoYml(x) for x in paths]
        return sorted(hpaths, key=lambda x: x.timestamp)

    @property
    def active_children(self) -> list:
        """
        Retrieve a list of active children from the active path.

        Returns:
            list: A list of active children.
        """
        return self.list_children(self.active_path)

    @property
    def finished_children(self) -> list:
        """
        Retrieve a list of finished child processes.

        Returns:
            list: A list of finished child processes.
        """
        return self.list_children(self.finished_path)

    @property
    def synced_children(self) -> list:
        """
        Retrieve a list of children from the synced path.

        Returns:
            list: A list of children from the synced path.
        """
        return self.list_children(self.synced_path)

    @property
    def children(self) -> list:
        """
        Retrieve a sorted list of all child objects.

        This method combines active, finished, and synced children into a single list
        and sorts them based on their timestamp attribute.

        Returns:
            list: A sorted list of all child objects.
        """
        all_children = (
            self.active_children + self.finished_children + self.synced_children
        )
        return sorted(all_children, key=lambda x: x.timestamp)

    @property
    def misc_files(self) -> List[Path]:
        """
        Retrieve a list of miscellaneous files from the target directory.

        This method scans the target directory and returns a list of files that do not have
        the extensions '.yml', '.hlo', or '.lock'.

        Returns:
            List[Path]: A list of Path objects representing the miscellaneous files.
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
        """
        Retrieve a list of lock files in the target directory.

        This method searches the target directory for files with the ".lock" suffix
        and returns a list of their paths.

        Returns:
            List[Path]: A list of paths to the lock files in the target directory.
        """
        return [
            x for x in self.targetdir.glob("*") if x.is_file() and x.suffix == ".lock"
        ]

    @property
    def hlo_files(self) -> List[Path]:
        """
        Retrieve a list of .hlo files from the target directory.

        Returns:
            List[Path]: A list of Path objects representing .hlo files in the target directory.
        """
        return [
            x for x in self.targetdir.glob("*") if x.is_file() and x.suffix == ".hlo"
        ]

    @property
    def parent_path(self) -> Path:
        """
        Determines the parent path based on the type of the current instance.

        If the type is "sequence", it returns the target path.
        Otherwise, it searches for YAML files in the parent directories of
        active_path, finished_path, and synced_path, and returns the first match.

        Returns:
            Path: The parent path based on the type or the first matching YAML file.
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
        """
        Writes metadata to the target file in YAML format.

        Args:
            meta_dict (dict): A dictionary containing metadata to be written.

        Raises:
            Exception: If there is an issue writing to the target file.
        """
        # with self.filelock:
        self.target.write_text(
            str(
                yml_dumps(meta_dict),
                encoding="utf-8",
            )
        )


class Progress:
    """
    Progress class to manage synchronization of Helao .yml and .prg files.

    Attributes:
        ymlpath (HelaoYml): Path to the Helao YAML file.
        prg (Path): Path to the progress file.
        dict (Dict): Dictionary to store progress data.

    Methods:
        __init__(path: Union[Path, str]):
            Initializes the Progress object with the given path.

        yml:
            Property to get the HelaoYml object from the ymlpath.

        list_unfinished_procs():
            Returns a pair of lists with non-synced s3 and api processes.

        read_dict():
            Reads the progress dictionary from the .prg file.

        write_dict(new_dict: Optional[Dict] = None):
            Writes the progress dictionary to the .prg file.

        s3_done:
            Property to check if s3 synchronization is done.

        api_done:
            Property to check if api synchronization is done.

        remove_prg():
            Removes the .prg file.
    """

    ymlpath: HelaoYml
    prg: Path
    dict: Dict

    def __init__(self, path: Union[Path, str]):
        """
        Initialize the Progress with the given path.

        Args:
            path (Union[Path, str]): The path to the .yml or .prg file.

        Raises:
            ValueError: If the provided path is not a valid .yml or .prg file.

        Notes:
            - If the path is a .yml file, it sets the `ymlpath` attribute.
            - If the path is a .prg file, it sets the `prg` attribute.
            - If the path is a string, it converts it to a Path object and performs the same checks.
            - If the `prg` attribute is not set, it derives it from the `yml` attribute.
            - If the .prg file does not exist, it initializes a dictionary with default values and writes it to the .prg file.
            - If the .prg file exists, it reads the dictionary from the file.
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

    @property
    def yml(self):
        """
        Parses the YAML file located at the specified path and returns a HelaoYml object.

        Returns:
            HelaoYml: An object representing the parsed YAML file.
        """
        return HelaoYml(self.ymlpath)

    def list_unfinished_procs(self):
        """
        Returns a pair of lists with non-synced S3 and API processes.

        This method checks the type of the YAML configuration. If the type is
        "experiment", it identifies processes that are present in the
        "process_groups" but not in "process_s3" and "process_api". These
        processes are considered unfinished and are returned as two separate
        lists: one for S3 and one for API. If the type is not "experiment",
        it returns two empty lists.

        Returns:
            tuple: A tuple containing two lists:
                - s3_unf (list): List of process groups not synced with S3.
                - api_unf (list): List of process groups not synced with API.
        """
        """Returns pair of lists with non-synced s3 and api processes."""
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
        """
        Reads a YAML file specified by `self.prg` and loads its contents into `self.dict`.

        This method uses the `yml_load` function to parse the YAML file and store the resulting dictionary in the `self.dict` attribute.
        """
        self.dict = yml_load(self.prg)

    def write_dict(self, new_dict: Optional[Dict] = None):
        """
        Writes a dictionary to a file in YAML format.

        Args:
            new_dict (Optional[Dict], optional): The dictionary to write. If None,
                                                 the instance's dictionary (`self.dict`)
                                                 will be written. Defaults to None.

        Returns:
            None
        """
        out_dict = self.dict if new_dict is None else new_dict
        # with self.prglock:
        self.prg.write_text(str(yml_dumps(out_dict)), encoding="utf-8")

    @property
    def s3_done(self):
        """
        Checks if the 's3' key in the dictionary is marked as done.

        Returns:
            bool: The value associated with the 's3' key in the dictionary.
        """
        return self.dict["s3"]

    @property
    def api_done(self):
        """
        Retrieves the value associated with the key "api" from the dictionary.

        Returns:
            The value associated with the key "api" in the dictionary.
        """
        return self.dict["api"]

    def remove_prg(self):
        """
        Removes the program file associated with the driver.

        This method unlinks (deletes) the program file (`self.prg`) from the filesystem.
        """
        # with self.prglock:
        self.prg.unlink()


class HelaoSyncer:
    """
    HelaoSyncer is a class responsible for synchronizing YAML files to S3 and an API.
    It manages tasks, handles file uploads, and ensures data consistency across different storage systems.

    Attributes:
        progress (Dict[str, Progress]): A dictionary to track the progress of tasks.
        base (Base): The base server instance.
        running_tasks (dict): A dictionary to keep track of currently running tasks.
        config_dict (dict): Configuration parameters for the syncer.
        world_config (dict): World configuration parameters.
        max_tasks (int): Maximum number of concurrent tasks.
        aws_session (boto3.Session): AWS session for S3 operations.
        s3 (boto3.client): S3 client for file uploads.
        s3r (boto3.resource): S3 resource for file operations.
        bucket (str): S3 bucket name.
        api_host (str): API host URL.
        sequence_objs (dict): Dictionary to store sequence objects.
        task_queue (asyncio.PriorityQueue): Priority queue for managing tasks.
        aiolock (asyncio.Lock): Asyncio lock for synchronization.
        syncer_loop (asyncio.Task): Asyncio task for the syncer loop.

    Methods:
        __init__(self, action_serv: Base, db_server_name: str = "DB"):
            Initializes the HelaoSyncer instance with the given action server and database server name.

        try_remove_empty(self, remove_target):
            Attempts to remove an empty directory and returns success status.

        cleanup_root(self):
            Removes leftover empty directories from the root.

        sync_exit_callback(self, task: asyncio.Task):
            Callback function to handle the completion of a sync task.

        syncer(self):
            Coroutine that runs the syncer loop, consuming tasks from the task queue.

        get_progress(self, yml_path: Path):
            Returns progress from the global dictionary and updates the YAML path if not found.

        enqueue_yml(self, upath: Union[Path, str], rank: int = 5, rank_limit: int = -5):
            Adds a YAML file to the sync queue with the specified priority.

        sync_yml(self, yml_path: Path, retries: int = 3, rank: int = 5, force_s3: bool = False, force_api: bool = False, compress: bool = False):
            Coroutine for syncing a single YAML file.

        update_process(self, act_yml: HelaoYml, act_meta: Dict):
            Updates processes in the experiment parent based on the action YAML and metadata.

        sync_process(self, exp_prog: Progress, force: bool = False):
            Pushes unfinished processes to S3 and API from experiment progress.

        to_s3(self, msg: Union[dict, Path], target: str, retries: int = 5, compress: bool = False):
            Uploads data to S3, either as a JSON object or a file.

        to_api(self, req_model: dict, meta_type: str, retries: int = 5):
            Sends a POST or PATCH request to the Modelyst API.

        list_pending(self, omit_manual_exps: bool = True):
            Finds and queues YAML files from the RUNS_FINISHED directory.

        finish_pending(self, omit_manual_exps: bool = True):
            Finds and queues sequence YAML files from the RUNS_FINISHED directory.

        reset_sync(self, sync_path: str):
            Resets a synced sequence zip or partially-synced sequence folder.

        shutdown(self):
            Placeholder method for shutting down the syncer.

        unsync_dir(self, sync_dir: str):
            Reverts a synced directory back to the RUNS_FINISHED state.
    """

    progress: Dict[str, Progress]
    base: Base
    running_tasks: dict

    def __init__(self, action_serv: Base, db_server_name: str = "DB"):
        """
        Initializes the SyncDriver instance.

        Args:
            action_serv (Base): The action server instance.
            db_server_name (str, optional): The name of the database server. Defaults to "DB".

        Attributes:
            base (Base): The action server instance.
            config_dict (dict): Configuration parameters for the driver.
            world_config (dict): World configuration from the action server.
            max_tasks (int): Maximum number of tasks allowed.
            aws_session (boto3.Session or None): AWS session if AWS configuration is provided.
            s3 (boto3.client or None): S3 client if AWS configuration is provided.
            s3r (boto3.resource or None): S3 resource if AWS configuration is provided.
            bucket (str): AWS S3 bucket name.
            api_host (str): API host address.
            sequence_objs (dict): Dictionary to store sequence objects.
            task_queue (asyncio.PriorityQueue): Priority queue for tasks.
            running_tasks (dict): Dictionary to store running tasks.
            aiolock (asyncio.Lock): Asynchronous lock.
            syncer_loop (asyncio.Task): Asynchronous task for the syncer loop.
        """
        self.base = action_serv
        self.config_dict = action_serv.server_cfg.get("params", {})
        self.world_config = action_serv.world_cfg
        self.max_tasks = self.config_dict.get("max_tasks", 8)
        # to load this driver on orch, we check the default "DB" key or take a manually-specified key
        if (
            not self.config_dict.get("aws_config_path", False)
            and db_server_name in self.world_config["servers"]
        ):
            self.config_dict = self.world_config["servers"][db_server_name].get(
                "params", {}
            )
        if "aws_config_path" in self.config_dict:
            os.environ["AWS_CONFIG_FILE"] = self.config_dict["aws_config_path"]
            self.aws_session = boto3.Session(
                profile_name=self.config_dict["aws_profile"]
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
        # self.task_set = set()
        self.running_tasks = {}
        self.aiolock = asyncio.Lock()
        # push happens via async task queue
        # processes are checked after each action push
        # pushing an exp before processes/actions have synced will first enqueue actions
        # then enqueue processes, then enqueue the exp again
        # exp progress must be in memory before actions are checked

        self.syncer_loop = asyncio.create_task(self.syncer(), name="syncer_loop")

    def try_remove_empty(self, remove_target):
        """
        Attempts to remove a directory if it is empty. If the directory contains subdirectories,
        it will recursively attempt to remove them if they are empty as well.

        Args:
            remove_target (str): The path of the directory to be removed.

        Returns:
            bool: True if the directory (and any subdirectories) were successfully removed,
                  False otherwise.

        Raises:
            Exception: If an error occurs while attempting to remove the directory,
                       an error message will be logged.
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

    def cleanup_root(self):
        today = datetime.strptime(datetime.now().strftime("%Y%m%d"), "%Y%m%d")
        """
        Cleans up the root directory by removing empty directories.

        This method checks the directories specified in `chkdirs` ("RUNS_ACTIVE" and "RUNS_FINISHED")
        within the root directory defined in `world_config`. It iterates through the directories
        and removes any empty directories that are older than the current date.

        Directories are expected to be named with dates in the format "%Y%m%d" or "%Y%m%d.%H%M%S%f".
        If a directory is empty, it is removed. If the parent directory of the empty directory
        also becomes empty, it is removed as well.

        Raises:
            ValueError: If the directory names do not match the expected date formats.
        """
        chkdirs = ["RUNS_ACTIVE", "RUNS_FINISHED"]
        for cd in chkdirs:
            seq_dates = glob(os.path.join(self.world_config["root"], cd, "*", "*"))
            for datedir in seq_dates:
                try:
                    dateonly = datetime.strptime(os.path.basename(datedir), "%Y%m%d")
                except ValueError:
                    dateonly = datetime.strptime(
                        os.path.basename(datedir), "%Y%m%d.%H%M%S%f"
                    )
                if dateonly <= today:
                    seq_dirs = glob(os.path.join(datedir, "*"))
                    if len(seq_dirs) == 0:
                        self.try_remove_empty(datedir)
                    weekdir = os.path.dirname(datedir)
                    if len(glob(os.path.join(weekdir, "*"))) == 0:
                        self.try_remove_empty(weekdir)

    def sync_exit_callback(self, task: asyncio.Task):
        """
        Callback function to handle the completion of an asyncio task.

        This function is called when an asyncio task completes. It removes the task
        from the `running_tasks` dictionary if it exists.

        Args:
            task (asyncio.Task): The asyncio task that has completed.
        """
        task_name = task.get_name()
        if task_name in self.running_tasks:
            # LOGGER.info(f"Removing {task_name} from running_tasks.")
            self.running_tasks.pop(task_name)
        # else:
        #     self.base.print_message(
        #         f"{task_name} was already removed from running_tasks."
        #     )

    async def syncer(self):
        """
        Asynchronous method to continuously process tasks from a queue and manage their execution.

        This method runs an infinite loop that checks if the number of currently running tasks
        is less than the maximum allowed tasks. If so, it retrieves the next task from the queue
        and starts its execution if it is not already running.

        The method performs the following steps:
        1. Checks if the number of running tasks is less than the maximum allowed tasks.
        2. Retrieves the next task from the task queue.
        3. If the task is not already running, creates and starts an asynchronous task for it.
        4. Adds a callback to handle the task's completion.
        5. Waits for a short period before repeating the process.

        The tasks are expected to be YAML files, and the method ensures that each task is only
        processed once at a time.

        Attributes:
            running_tasks (dict): A dictionary to keep track of currently running tasks.
            max_tasks (int): The maximum number of tasks that can run concurrently.
            task_queue (asyncio.Queue): A queue from which tasks are retrieved.

        Returns:
            None
        """
        while True:
            if len(self.running_tasks) < self.max_tasks:
                # LOGGER.info("Getting next yml_target from queue.")
                rank, yml_path = await self.task_queue.get()
                # self.task_set.remove(yml_path.name)
                # self.base.print_message(
                #     f"Acquired {yml_target.name} with priority {rank}."
                # )
                if yml_path.name not in self.running_tasks:
                    # self.base.print_message(
                    #     f"Creating sync task for {yml_target.name}."
                    # )
                    self.running_tasks[yml_path.name] = asyncio.create_task(
                        self.sync_yml(yml_path=yml_path, rank=rank),
                        name=yml_path.name,
                    )
                    self.running_tasks[yml_path.name].add_done_callback(
                        self.sync_exit_callback
                    )
                # else:
                #     print_message(f"{yml_target} sync is already in progress.")
            await asyncio.sleep(0.1)

    def get_progress(self, yml_path: Path):
        """
        Retrieves or initializes the progress of a given YAML file.

        This method checks if the specified YAML file exists. If it does not exist,
        it initializes a new `HelaoYml` object, checks its paths, creates a `Progress`
        object, and writes the progress dictionary. If the YAML file exists, it simply
        initializes a `Progress` object with the given path.

        Args:
            yml_path (Path): The path to the YAML file.

        Returns:
            Progress: An instance of the `Progress` class representing the progress
            of the specified YAML file.
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
        self, upath: Union[Path, str], rank: int = 5, rank_limit: int = -5
    ):
        """
        Enqueue a YAML file to the task queue with a specified rank.

        Args:
            upath (Union[Path, str]): The path to the YAML file to be enqueued.
            rank (int, optional): The priority rank for the task. Defaults to 5.
            rank_limit (int, optional): The minimum rank allowed for enqueuing. Defaults to -5.

        Returns:
            None

        Notes:
            - If the rank is below the rank_limit, the task will not be enqueued.
            - If the task is already running, it will not be enqueued.
            - The task is added to the queue with the specified rank if it passes the checks.
        """
        yml_path = Path(upath) if isinstance(upath, str) else upath
        if rank < rank_limit:
            LOGGER.info(
                f"{str(yml_path)} re-queue rank is under {rank_limit}, skipping enqueue request."
            )
        # elif yml_path.name in self.task_set:
        #     self.base.print_message(
        #         f"{str(yml_path)} is already queued, skipping enqueue request."
        #     )
        elif yml_path.name in self.running_tasks:
            LOGGER.info(
                f"{str(yml_path)} is already running, skipping enqueue request."
            )
        else:
            # self.task_set.add(yml_path.name)
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
        """
        Synchronize a YAML file with S3 and API.

        This function handles the synchronization of a YAML file by performing the following steps:
        1. Check if the YAML file exists and if it is already synced.
        2. Check the status of the YAML file and its children.
        3. Push files to S3 if the YAML file is of type 'action'.
        4. Finish processes for 'experiment' type YAML files.
        5. Patch the model and push the YAML file to S3 and API.
        6. Move files to a synced directory and clean up.

        Args:
            yml_path (Path): The path to the YAML file.
            retries (int, optional): Number of retries for syncing processes. Defaults to 3.
            rank (int, optional): Priority rank for the sync queue. Defaults to 5.
            force_s3 (bool, optional): Force push to S3 even if already done. Defaults to False.
            force_api (bool, optional): Force push to API even if already done. Defaults to False.
            compress (bool, optional): Compress files before pushing to S3. Defaults to False.

        Returns:
            dict: A dictionary containing the progress information, excluding 'process_metas'.
        """
        if not yml_path.exists():
            # self.base.print_message(
            #     f"{str(yml_path)} does not exist, assume yml has moved to synced."
            # )
            return True
        prog = self.get_progress(yml_path)
        if not prog:
            # self.base.print_message(
            #     f"{str(yml_path)} does not exist, assume yml has moved to synced."
            # )
            return True

        meta = copy(prog.yml.meta)

        if prog.yml.status == "synced":
            # self.base.print_message(
            #     f"Cannot sync {str(prog.yml.target)}, status is already 'synced'."
            # )
            return True

        # self.base.print_message(
        #     f"{str(prog.yml.target)} status is not synced, checking for finished."
        # )

        if prog.yml.status == "active":
            # self.base.print_message(
            #     f"Cannot sync {str(prog.yml.target)}, status is not 'finished'."
            # )
            return False

        # LOGGER.info(f"{str(prog.yml.target)} status is finished, proceeding.")

        # first check if child objects are registered with API (non-actions)
        if prog.yml.type != "action":
            if prog.yml.active_children:
                LOGGER.info(
                    f"Cannot sync {str(prog.yml.target)}, children are still 'active'."
                )
                return False
            if prog.yml.finished_children:
                # self.base.print_message(
                #     f"Cannot sync {str(prog.yml.target)}, children are not 'synced'."
                # )
                # self.base.print_message(
                #     "Adding 'finished' children to sync queue with highest priority."
                # )
                for child in prog.yml.finished_children:
                    if child.target.name not in self.running_tasks:
                        await self.enqueue_yml(child.target, rank - 1)
                        self.base.print_message(str(child.target))
                # self.base.print_message(
                #     f"Re-adding {str(prog.yml.target)} to sync queue with high priority."
                # )
                self.running_tasks.pop(prog.yml.target.name)
                await self.enqueue_yml(prog.yml.target, rank)
                LOGGER.info(f"{str(prog.yml.target)} re-queued, exiting.")
                return False

        # LOGGER.info(f"{str(prog.yml.target)} children are synced, proceeding.")

        # next push files to S3 (actions only)
        if prog.yml.type == "action":
            # re-check file lists
            # LOGGER.info(f"Checking file lists for {prog.yml.target.name}")
            prog.dict["files_pending"] += [
                str(p)
                for p in prog.yml.hlo_files + prog.yml.misc_files
                if p not in prog.dict["files_pending"]
                and p not in prog.dict["files_s3"]
            ]
            # push files to S3
            while prog.dict.get("files_pending", []):
                for sp in prog.dict["files_pending"]:
                    fp = Path(sp)
                    LOGGER.info(f"Pushing {sp} to S3 for {prog.yml.target.name}")
                    if fp.suffix == ".hlo":
                        if fp.stat().st_size < 1024**3:  # 1GB
                            file_s3_key = (
                                f"raw_data/{meta['action_uuid']}/{fp.name}.json"
                            )
                            if compress:
                                file_s3_key += ".gz"
                            LOGGER.info("Parsing hlo dicts.")
                            try:
                                file_meta, file_data = read_hlo(sp)
                            except Exception as err:
                                str_err = "".join(
                                    traceback.format_exception(
                                        type(err), err, err.__traceback__
                                    )
                                )
                                self.base.print_message(str_err)
                                file_meta = {}
                                file_data = {}
                            msg = {"meta": file_meta, "data": file_data}
                        else:
                            LOGGER.info(
                                "hlo file larger than 1GB, converting to parquet."
                            )
                            file_s3_key = (
                                f"raw_data/{meta['action_uuid']}/{fp.stem}.parquet"
                            )
                            try:
                                parquet_path = str(fp).replace(".hlo", ".parquet")
                                hlo_to_parquet(fp, parquet_path)
                                msg = Path(parquet_path)
                            except Exception as err:
                                str_err = "".join(
                                    traceback.format_exception(
                                        type(err), err, err.__traceback__
                                    )
                                )
                                self.base.print_message(str_err)
                                msg = None
                    else:
                        rel_posix_path = str(
                            fp.relative_to(prog.yml.targetdir)
                        ).replace("\\", "/")
                        file_s3_key = f"raw_data/{meta['action_uuid']}/{rel_posix_path}"
                        msg = fp
                    LOGGER.info(f"Destination: {file_s3_key}")
                    file_success = await self.to_s3(
                        msg=msg,
                        target=file_s3_key,
                        compress=compress,
                    )
                    if file_success:
                        LOGGER.info("Removing file from pending list.")
                        prog.dict["files_pending"].remove(sp)
                        LOGGER.info(f"Adding file to S3 dict. {fp.name}: {file_s3_key}")
                        prog.dict["files_s3"].update({fp.name: file_s3_key})
                        LOGGER.info(f"Updating progress: {prog.dict}")
                        prog.write_dict()

                        # update files list with uploaded filename
                        if fp.name != os.path.basename(file_s3_key):
                            file_idx = [
                                i
                                for i, x in enumerate(meta["files"])
                                if x["file_name"]
                                == str(fp.relative_to(prog.yml.targetdir))
                            ][0]
                            fileinfo = FileInfo(**meta["files"].pop(file_idx))
                            fileinfo.file_name = str(
                                fp.relative_to(prog.yml.targetdir)
                            ).replace("\\", "/")
                            if fileinfo.file_type.endswith(
                                "helao__file"
                            ):  # generic file
                                fileinfo.file_type = fileinfo.file_type.replace(
                                    "helao__file", f"{file_s3_key.split('.')[-1]}__file"
                                )
                            meta["files"].append(fileinfo.model_dump())
                        if isinstance(msg, Path):
                            LOGGER.info("cleaning up parquet file")
                            msg.unlink()

        # if prog.yml is an experiment first check processes before pushing to API
        if prog.yml.type == "experiment":
            LOGGER.info(f"Finishing processes for {prog.yml.target.name}")
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

        LOGGER.info(f"Patching model for {prog.yml.target.name}")
        patched_meta = {MOD_PATCH.get(k, k): v for k, v in meta.items()}
        meta = MOD_MAP[prog.yml.type](**patched_meta).clean_dict(strip_private=True)

        # patch technique lists in meta
        tech_name = meta.get("technique_name", "NA")
        if isinstance(tech_name, list):
            split_technique = tech_name[meta.get("action_split", 0)]
            meta["technique_name"] = split_technique

        # next push prog.yml to S3
        if not prog.s3_done or force_s3:
            LOGGER.info(f"Pushing prog.yml->json to S3 for {prog.yml.target.name}")
            uuid_key = patched_meta[f"{prog.yml.type}_uuid"]
            meta_s3_key = f"{prog.yml.type}/{uuid_key}.json"
            s3_success = await self.to_s3(meta, meta_s3_key)
            if s3_success:
                prog.dict["s3"] = True
                prog.write_dict()

        # next push prog.yml to API
        if not prog.api_done or force_api:
            LOGGER.info(f"Pushing prog.yml to API for {prog.yml.target.name}")
            api_success = await self.to_api(meta, prog.yml.type)
            LOGGER.info(f"API push returned {api_success} for {prog.yml.target.name}")
            if api_success:
                prog.dict["api"] = True
                prog.write_dict()

        # get yml target name for popping later (after seq zip removes yml)
        yml_target_name = prog.yml.target.name
        yml_type = prog.yml.type

        # move to synced
        if prog.s3_done and prog.api_done:

            LOGGER.info(f"Moving files to RUNS_SYNCED for {yml_target_name}")
            for lock_path in prog.yml.lock_files:
                lock_path.unlink()
            for file_path in prog.yml.misc_files + prog.yml.hlo_files:
                LOGGER.info(f"Moving {str(file_path)}")
                move_success = move_to_synced(file_path)
                while not move_success:
                    LOGGER.info(f"{file_path} is in use, retrying.")
                    sleep(1)
                    move_success = move_to_synced(file_path)

            # finally move yaml and update target
            LOGGER.info(f"Moving {yml_target_name} to RUNS_SYNCED")
            # with prog.yml.filelock:
            yml_success = move_to_synced(yml_path)
            if yml_success:
                result = prog.yml.cleanup()
                LOGGER.info(f"Cleanup {yml_target_name} {result}.")
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
                LOGGER.info(f"Removing children from progress: {children}.")
                for childyml in children:
                    # LOGGER.info(f"Clearing {childprog.yml.target.name}")
                    finished_child_path = childyml.finished_path.parent
                    if finished_child_path.exists():
                        self.try_remove_empty(str(finished_child_path))
                    # try:
                    #     self.progress.pop(childprog.yml.target.name)
                    # except Exception as err:
                    #     self.base.print_message(
                    #         f"Could not remove {childprog.yml.target.name}: {err}"
                    #     )
                self.try_remove_empty(str(prog.yml.finished_path.parent))

            if yml_type == "sequence":
                LOGGER.info(f"Zipping {prog.yml.target.parent.name}.")
                zip_target = prog.yml.target.parent.parent.joinpath(
                    f"{prog.yml.target.parent.name}.zip"
                )
                LOGGER.info(
                    f"Full sequence has synced, creating zip: {str(zip_target)}"
                )
                zip_dir(prog.yml.target.parent, zip_target)
                self.cleanup_root()
                # LOGGER.info(f"Removing sequence from progress.")
                # self.progress.pop(prog.yml.target.name)

            LOGGER.info(f"Removing {yml_target_name} from running_tasks.")
            self.running_tasks.pop(yml_target_name)

            # if action contributes processes, update processes
            if yml_type == "action" and meta.get("process_contrib", False):
                exp_prog = self.update_process(prog.yml, meta)
                await self.sync_process(exp_prog)

        return_dict = {k: d for k, d in prog.dict.items() if k != "process_metas"}
        return return_dict

    def update_process(self, act_yml: HelaoYml, act_meta: Dict):
        """
        Updates the process metadata and progress for a given action.

        Args:
            act_yml (HelaoYml): The YAML configuration object for the action.
            act_meta (Dict): Metadata dictionary for the action.

        Returns:
            The updated experiment progress object.

        The function performs the following steps:
        1. Retrieves the experiment progress from the given path.
        2. Handles legacy experiments that do not have a process list.
        3. Updates the process metadata and progress for the current action.
        4. Deduplicates sample lists if necessary.
        5. Registers the finished action in the process actions done list.
        6. Writes the updated progress dictionary to the file.
        """
        exp_path = Path(act_yml.parent_path)
        exp_prog = self.get_progress(exp_path)
        # with exp_prog.prglock:
        act_idx = act_meta["action_order"]
        # handle legacy experiments (no process list)
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
            exp_prog.dict["process_groups"][pidx].append(act_idx)
        else:
            pidx = [
                k for k, l in exp_prog.dict["process_groups"].items() if act_idx in l
            ][0]

            # if exp_prog doesn't yet have metadict, create one
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
                process_meta["action_list"] = []

            else:
                process_meta = exp_prog.dict["process_metas"][pidx]

            # update experiment progress with action
            process_meta["action_list"].append(
                ShortActionModel(**act_meta).clean_dict(strip_private=True)
            )

            # LOGGER.info(f"current experiment progress:\n{exp_prog.dict}")
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
                    process_meta[new_name] = contrib
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
                        for x in process_meta["action_list"]
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
                            # self.base.print_message(
                            #     "no action_uuid for {sample_label}, using listed order"
                            # )
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
            # register finished action in process_actions_done {order: ymltargetname}
            exp_prog = self.get_progress(exp_path)
            exp_prog.dict["process_metas"][pidx] = process_meta
            exp_prog.dict["process_actions_done"].update({act_idx: act_yml.target.name})
            exp_prog.write_dict()
        return exp_prog

    async def sync_process(self, exp_prog: Progress, force: bool = False):
        """
        Synchronizes the progress of processes by checking unfinished processes and
        pushing their metadata to S3 or an API if certain conditions are met.

        Args:
            exp_prog (Progress): The progress object containing the state of the experiment.
            force (bool, optional): If True, forces the synchronization regardless of other conditions. Defaults to False.

        Returns:
            Progress: The updated progress object after synchronization.

        The method performs the following steps:
        1. Checks for unfinished processes in S3 and API.
        2. For each unfinished process in S3:
            - Determines if the process should be pushed based on the `force` flag or other conditions.
            - If conditions are met, writes the process metadata to a local YAML file and syncs it to S3.
            - Updates the progress object to reflect the synchronization.
        3. For each unfinished process in the API:
            - Determines if the process should be pushed based on the completion of process actions.
            - If conditions are met, syncs the process metadata to the API.
            - Updates the progress object to reflect the synchronization.
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
                    push_condition = False
                    sync_path = os.path.dirname(str(exp_prog.prg))
                    LOGGER.warning(
                        f"Cannot sync experiment because process index {pidx} is missing. See {str(exp_prog.yml.target)}"
                    )
                    self.reset_sync(sync_path)
                    await self.enqueue_yml(str(exp_prog.yml.target))
                    return exp_prog
                meta = exp_prog.dict["process_metas"][pidx]
                uuid_key = meta["process_uuid"]
                model = ProcessModel(**meta).clean_dict(strip_private=True)
                # write to local yml
                save_dir = os.path.dirname(
                    os.path.join(
                        self.base.helaodirs.process_root,
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
            gids = exp_prog.dict["process_groups"][pidx]
            if all(i in exp_prog.dict["process_actions_done"] for i in gids):
                meta = exp_prog.dict["process_metas"][pidx]
                model = ProcessModel(**meta).clean_dict(strip_private=True)
                api_success = await self.to_api(model, "process")
                if api_success:
                    exp_prog.dict["process_api"].append(pidx)
                    exp_prog.write_dict()
        return exp_prog

    async def to_s3(
        self,
        msg: Union[dict, Path],
        target: str,
        retries: int = 5,
        compress: bool = False,
    ):
        """
        Uploads a message or file to an S3 bucket with optional retries and compression.

        Args:
            msg (Union[dict, Path]): The message to upload, either as a dictionary or a file path.
            target (str): The target path in the S3 bucket.
            retries (int, optional): The number of retry attempts in case of failure. Defaults to 5.
            compress (bool, optional): Whether to compress the message before uploading. Defaults to False.

        Returns:
            bool: True if the upload was successful, False otherwise.

        Raises:
            Exception: If an unexpected error occurs during the upload process.
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
                LOGGER.info("Converting path to str")
                uploadee = str(msg)
                uploader = self.s3.upload_file
            for i in range(retries + 1):
                if i > 0:
                    LOGGER.info(f"S3 retry [{i}/{retries}]: {self.bucket}, {target}")
                try:
                    uploader(uploadee, self.bucket, target)
                    return True
                except Exception as err:
                    _ = "".join(
                        traceback.format_exception(type(err), err, err.__traceback__)
                    )
                    self.base.print_message(err)
                    await asyncio.sleep(30)
            LOGGER.info(f"Did not upload {target} after {retries} tries.")
            return False
        except Exception:
            LOGGER.error(f"Could not push {target}.", exc_info=True)
            return False

    async def to_api(self, req_model: dict, meta_type: str, retries: int = 5):
        """
        Pushes a request model to an API endpoint asynchronously with retry logic.

        Args:
            req_model (dict): The request model to be sent to the API.
            meta_type (str): The type of metadata being sent.
            retries (int, optional): The number of retry attempts in case of failure. Defaults to 5.

        Returns:
            bool: True if the API push was successful, False otherwise.

        Raises:
            Exception: If an exception occurs during the API request.

        Notes:
            - If the API host is not configured, the function will skip the API push and return True.
            - The function will attempt to create a new resource with a POST request. If a 400 status code is received, it will switch to a PATCH request to update the resource.
            - If all retry attempts fail, the function will attempt to log the failure to a separate endpoint.
        """
        if self.api_host is None:
            LOGGER.info("Modelyst API is not configured. Skipping to API push.")
            return True
        req_url = f"https://{self.api_host}/{PLURALS[meta_type]}/"
        # LOGGER.info(f"preparing API push to {req_url}")
        # meta_name = req_model.get(
        #     f"{meta_type.replace('process', 'technique')}_name",
        #     req_model["experiment_name"],
        # )
        meta_uuid = req_model[f"{meta_type}_uuid"]
        LOGGER.info(f"attempting API push for {meta_type}: {meta_uuid}")
        try_create = True
        api_success = False
        last_status = 0
        last_response = {}
        LOGGER.debug("creating async request session")
        async with aiohttp.ClientSession() as session:
            for i in range(retries):
                if not api_success:
                    LOGGER.debug(f"session attempt {i}")
                    req_method = session.post if try_create else session.patch
                    api_str = f"API {'POST' if try_create else 'PATCH'}"
                    try:
                        LOGGER.debug("trying request")
                        async with req_method(req_url, json=req_model) as resp:
                            LOGGER.debug("response received")
                            if resp.status == 200:
                                api_success = True
                            elif resp.status == 400:
                                try_create = False
                            LOGGER.info(
                                f"[{i+1}/{retries}] {api_str} {meta_uuid} returned status: {resp.status}"
                            )
                            last_response = await resp.json()
                            LOGGER.info(
                                f"[{i+1}/{retries}] {api_str} {meta_uuid} response: {last_response}"
                            )
                            last_status = resp.status
                    except Exception as e:
                        LOGGER.info(f"[{i+1}/{retries}] an exception occurred: {e}")
                        await asyncio.sleep(30)
                else:
                    break
            if not api_success:
                meta_s3_key = f"{meta_type}/{meta_uuid}.json"
                fail_model = {
                    "endpoint": f"https://{self.api_host}/{PLURALS[meta_type]}/",
                    "method": "POST" if try_create else "PATCH",
                    "status_code": last_status,
                    "detail": last_response.get("detail", ""),
                    "data": req_model,
                    "s3_files": [
                        {
                            "bucket_name": self.bucket,
                            "key": meta_s3_key,
                        }
                    ],
                }
                fail_url = f"https://{self.api_host}/failed"
                async with aiohttp.ClientSession() as session:
                    for _ in range(retries):
                        try:
                            async with session.post(fail_url, json=fail_model) as resp:
                                if resp.status == 200:
                                    LOGGER.info(
                                        f"successful debug API push for {meta_type}: {meta_uuid}"
                                    )
                                    break
                                LOGGER.info(
                                    f"failed debug API push for {meta_type}: {meta_uuid}"
                                )
                                LOGGER.info(f"response: {await resp.json()}")
                        except TimeoutError:
                            LOGGER.info(
                                f"unable to post failure model for {meta_type}: {meta_uuid}"
                            )
                            await asyncio.sleep(30)
        return api_success

    def list_pending(self, omit_manual_exps: bool = True):
        """
        Lists pending sequences in the RUNS_FINISHED directory.

        This method searches for sequence files in the RUNS_FINISHED directory
        and returns a list of pending sequences. By default, it omits sequences
        that are manually orchestrated.

        Args:
            omit_manual_exps (bool): If True, sequences containing 'manual_orch_seq'
                                     in their filename will be omitted from the list.
                                     Defaults to True.

        Returns:
            list: A list of file paths to the pending sequence files.
        """
        finished_dir = str(self.base.helaodirs.save_root).replace(
            "RUNS_ACTIVE", "RUNS_FINISHED"
        )
        pending = glob(os.path.join(finished_dir, "**", "*-seq.yml"), recursive=True)
        if omit_manual_exps:
            pending = [x for x in pending if "manual_orch_seq" not in x]
        LOGGER.info(f"Found {len(pending)} pending sequences in RUNS_FINISHED.")
        return pending

    async def finish_pending(self, omit_manual_exps: bool = True):
        """
        Processes and enqueues pending sequences from the RUNS_FINISHED directory.

        This method identifies pending sequences, logs the number of sequences to be enqueued,
        and processes each sequence. If a corresponding .progress file exists in the RUNS_SYNCED
        directory, it resets the sync state. Finally, it enqueues each sequence for further processing.

        Args:
            omit_manual_exps (bool): If True, manual experiments are omitted from the pending list.
                                     Defaults to True.

        Returns:
            list: A list of pending sequences that were processed and enqueued.
        """
        pending = self.list_pending(omit_manual_exps)
        LOGGER.info(f"Enqueueing {len(pending)} sequences from RUNS_FINISHED.")
        for pp in pending:
            if os.path.exists(
                pp.replace("RUNS_FINISHED", "RUNS_SYNCED").replace(".yml", ".progress")
            ):
                self.reset_sync(
                    os.path.dirname(pp).replace("RUNS_FINISHED", "RUNS_SYNCED")
                )
            await self.enqueue_yml(pp)
        return pending

    def reset_sync(self, sync_path: str):
        """
        Resets the synchronization state of a given path.

        This method handles both zip files and directories. For zip files, it extracts
        the contents (excluding .prg and .lock files) to a corresponding directory in
        the RUNS_FINISHED path. For directories, it removes all .prg, .progress, and .lock
        files and moves the directory back to the RUNS_FINISHED path.

        Args:
            sync_path (str): The path to reset. This can be either a zip file or a directory.

        Returns:
            bool: True if the reset was successful, False otherwise.

        Raises:
            FileNotFoundError: If the provided path does not exist.
            ValueError: If the provided path is not in the RUNS_SYNCED directory.
        """
        if not os.path.exists(sync_path):
            LOGGER.info(f"{sync_path} does not exist.")
            return False
        if "RUNS_SYNCED" not in sync_path:
            LOGGER.info(f"Cannot reset path that's not in RUNS_SYNCED: {sync_path}")
            return False
        ## if path is a zip
        if sync_path.endswith(".zip"):
            zf = ZipFile(sync_path)
            if any(x.endswith("-seq.prg") for x in zf.namelist()):
                seqzip_dir = os.path.dirname(sync_path)
                dest = os.path.join(
                    seqzip_dir.replace("RUNS_SYNCED", "RUNS_FINISHED"),
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
        pass

    def unsync_dir(self, sync_dir: str):
        """
        Reverts the synchronization of a directory by performing the following actions:

        1. Removes files with extensions .lock, .progress, or .prg.
        2. Moves all other files to a corresponding directory in "RUNS_FINISHED".

        Args:
            sync_dir (str): The path to the directory to be unsynchronized.

        Logs:
            A warning message indicating the successful reversion of the directory.
        """
        for fp in glob(os.path.join(sync_dir, "**", "*"), recursive=True):
            if fp.endswith(".lock") or fp.endswith(".progress") or fp.endswith(".prg"):
                os.remove(fp)
            elif not os.path.isdir(fp):
                tp = os.path.dirname(fp.replace("RUNS_SYNCED", "RUNS_FINISHED"))
                os.makedirs(tp, exist_ok=True)
                shutil.move(fp, tp)
        LOGGER.warning(f"Successfully reverted {sync_dir}")
