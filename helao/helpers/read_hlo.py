__all__ = ["read_hlo", "HelaoData"]

import os
import json
import builtins
from pathlib import Path
from typing import Tuple
from collections import defaultdict
from glob import glob
from ruamel.yaml import YAML


def read_hlo(path: str) -> Tuple[dict, dict]:
    "Parse .hlo file into tuple of dictionaries containing metadata and data."
    path_to_hlo = Path(path)
    with path_to_hlo.open() as f:
        lines = f.readlines()

    sep_index = lines.index("%%\n")

    yaml = YAML(typ="safe")
    meta = yaml.load("".join(lines[:sep_index]))

    data = defaultdict(list)
    for line in lines[sep_index + 1 :]:
        line_dict = json.loads(line)
        # print(line_dict)
        for k, v in line_dict.items():
            if isinstance(v, list):
                data[k] += v
            else:
                data[k].append(v)

    return meta, data


class HelaoData:
    def __init__(self, target: str):
        self.ord = ["seq", "exp", "act"]
        self.abbrd = {"seq": "sequence", "exp": "experiment", "act": "action"}
        self.target = target
        if os.path.isdir(self.target):
            self.ymldir = self.target
            self.ymlpath = glob(os.path.join(self.target, "*.yml"))[0]
        else:
            self.ymldir = os.path.dirname(self.target)
            self.ymlpath = target
        self.type = self.ymlpath.split("-")[-1].replace(".yml", "")
        self.seq = [
            HelaoData(x)
            for x in sorted(glob(os.path.join(self.ymldir, "*", "*-seq.yml")))
        ]
        self.exp = [
            HelaoData(x)
            for x in sorted(glob(os.path.join(self.ymldir, "*", "*-exp.yml")))
        ]
        self.act = [
            HelaoData(x)
            for x in sorted(glob(os.path.join(self.ymldir, "*", "*-act.yml")))
        ]
        yaml = YAML(typ="unsafe")
        self.yml = yaml.load("".join(builtins.open(self.ymlpath, "r").readlines()))
        self.name = self.yml.get(f"{self.abbrd[self.type]}_name", "NA")
        self.params = self.yml.get(f"{self.abbrd[self.type]}_params", {})
        self.uuid = self.yml[f"{self.abbrd[self.type]}_uuid"]
        self.timestamp = self.yml[f"{self.abbrd[self.type]}_timestamp"]
        self.data_files = glob(os.path.join(self.ymldir, "*.hlo"))
        if self.data_files:
            self.data = lambda: read_hlo(self.data_files[0])
        else:
            self.data = None
        self.children = self.seq + self.exp + self.act

    def ls(self):
        return print(
            "\n".join(
                [self.__repr__()]
                + [f"  [{i}] " + x.__repr__() for i, x in enumerate(self.children)]
            )
        )

    def __repr__(self):
        return f"{self.abbrd[self.type]}: {self.name} @ {self.timestamp} CONTAINING {len(self.children)} children"
