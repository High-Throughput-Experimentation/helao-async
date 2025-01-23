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

__all__ = ["read_hlo"]

import orjson
from pathlib import Path
from typing import Tuple
from collections import defaultdict

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

