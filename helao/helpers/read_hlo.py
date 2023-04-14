__all__ = ["read_hlo", "HelaoData"]

import os
import json
import builtins
from pathlib import Path
from typing import Tuple
from collections import defaultdict
from glob import glob
from ruamel.yaml import YAML
from zipfile import ZipFile
import zipfile


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
    def __init__(self, target: str, **kwargs):
        yaml = YAML(typ="unsafe")
        self.ord = ["seq", "exp", "act"]
        self.abbrd = {"seq": "sequence", "exp": "experiment", "act": "action"}
        self.target = target
        if self.target.endswith(
            ".zip"
        ):  # this will always be a zipped sequence, helao does not zip actions, experiments
            with ZipFile(target, "r") as zf:
                if "zflist" in kwargs.keys():
                    self.zflist = kwargs["zflist"]
                else:
                    self.zflist = [p for p in zf.namelist() if not p.endswith("/")]
                if "ztarget" in kwargs.keys():
                    self.ymlpath = kwargs["ztarget"]
                else:
                    self.ymlpath = [p for p in self.zflist if p.endswith("-seq.yml")][0]
                self.ymldir = os.path.dirname(self.ymlpath)
                self.type = self.ymlpath.split("-")[-1].replace(".yml", "")
                self.yml = yaml.load(zf.open(self.ymlpath).read().decode("UTF-8"))
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
                    if p.endswith("-exp.yml") and p.startswith(self.ymldir)
                ]
                self.act = [
                    HelaoData(self.target, zflist=self.zflist, ztarget=p)
                    for p in sorted(
                        sub_acts,
                        key=lambda x: float(
                            os.path.basename(os.path.dirname(x)).split("__")[0]
                        ),
                    )
                    if p.endswith("-act.yml") and p.startswith(self.ymldir)
                ]
            self.data_files = [
                p
                for p in self.zflist
                if p.endswith(".hlo")
                and p.startswith(self.ymldir)
                and os.path.dirname(p) == self.ymldir
            ]
        else:
            if os.path.isdir(self.target):
                self.ymldir = self.target
                self.ymlpath = glob(os.path.join(self.target, "*.yml"))[0]
            elif target.endswith(".yml"):
                self.ymldir = os.path.dirname(self.target)
                self.ymlpath = target
            self.type = self.ymlpath.split("-")[-1].replace(".yml", "")
            self.yml = yaml.load("".join(builtins.open(self.ymlpath, "r").readlines()))
            self.seq = [
                HelaoData(x)
                for x in sorted(
                    glob(os.path.join(self.ymldir, "*", "*-seq.yml")),
                    key=lambda x: float(
                        os.path.basename(os.path.dirname(x)).split("__")[0]
                    ),
                )
            ]
            self.exp = [
                HelaoData(x)
                for x in sorted(
                    glob(os.path.join(self.ymldir, "*", "*-exp.yml")),
                    key=lambda x: float(
                        os.path.basename(os.path.dirname(x)).split("__")[0]
                    ),
                )
            ]
            self.act = [
                HelaoData(x)
                for x in sorted(
                    glob(os.path.join(self.ymldir, "*", "*-act.yml")),
                    key=lambda x: float(
                        os.path.basename(os.path.dirname(x)).split("__")[0]
                    ),
                )
            ]
            self.data_files = glob(os.path.join(self.ymldir, "*.hlo"))

        self.name = self.yml.get(f"{self.abbrd[self.type]}_name", "NA")
        self.params = self.yml.get(f"{self.abbrd[self.type]}_params", {})
        self.uuid = self.yml[f"{self.abbrd[self.type]}_uuid"]
        self.timestamp = self.yml[f"{self.abbrd[self.type]}_timestamp"]
        self.samples_in = self.yml.get(f"samples_in", [])
        self.children = self.seq + self.exp + self.act

    @property
    def ls(self):
        return print(
            "\n".join(
                [self.__repr__()]
                + [f"  [{i}] " + x.__repr__() for i, x in enumerate(self.children)]
            )
        )

    def read_hlo(self, hlotarget):
        if self.target.endswith(".zip"):
            with ZipFile(self.target, "r") as zf:
                lines = zf.open(hlotarget).readlines()

            lines = [x.decode("UTF-8").replace("\r\n", "\n") for x in lines]
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
        else:
            return read_hlo(hlotarget)

    def read_file(self, hlotarget):
        bytes = zipfile.Path(self.target, hlotarget).read_bytes()
        return bytes

    @property
    def data(self):
        return self.read_hlo(self.data_files[0])

    def __repr__(self):
        return f"{self.abbrd[self.type]}: {self.name} @ {self.timestamp} CONTAINING {len(self.children)} children"
