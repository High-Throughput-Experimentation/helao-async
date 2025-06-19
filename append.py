"""
Utility for launching & appending servers to running server group

launch via 'python append.py {running_config_prefix} {append_config_prefix}'

"""

__all__ = ["appender"]

import os
import sys
from helao.helpers.config_loader import CONFIG

helao_repo_root = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.join(helao_repo_root, 'config'))
sys.path.append(helao_repo_root)
from helao import launcher
confPrefix = sys.argv[1]
appendPrefix = sys.argv[2]


def appender(confPrefix, appendPrefix):
    confDict = read_config(confPrefix, helao_repo_root)
    appenDict = read_config(appendPrefix, helao_repo_root)
    overlap = [k for k in appenDict["servers"].keys() if k in confDict["servers"].keys()]
    if overlap:
        print(f"config dict from '{appendPrefix}' overlaps with '{confPrefix}")
        return None
    else:
        confDict["servers"].update(appenDict["servers"])
        launcher(confPrefix, confDict, helao_repo_root)


if __name__ == "__main__":
    appender(confPrefix, appendPrefix)
