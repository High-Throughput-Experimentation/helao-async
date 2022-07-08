__all__ = ["read_hlo"]

import json
from ruamel.yaml import YAML
from pathlib import Path
from typing import Tuple
from collections import defaultdict


def read_hlo(path: str) -> Tuple[dict, dict]:
    "Parse .hlo file into tuple of dictionaries containing metadata and data."
    path_to_hlo = Path(path)
    with path_to_hlo.open() as f:
        lines = f.readlines()

    sep_index = lines.index('%%\n')

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
