"""
Utility for launching & appending servers to running server group

launch via 'python append.py {running_config_prefix} {append_config_prefix}'

"""

__all__ = ["appender"]

import os
import sys

import launch
from launch import launcher
from helao.helpers import helao_logging as logging
from helao.helpers.config_loader import read_config
from helao.helpers.helao_dirs import helao_dirs

confPrefix = sys.argv[1]
appendPrefix = sys.argv[2]
helao_repo_root = os.path.dirname(os.path.realpath(__file__))


def appender(confPrefix, appendPrefix):
    confDict = read_config(confPrefix)
    appenDict = read_config(appendPrefix)
    overlap = [
        k for k in appenDict["servers"].keys() if k in confDict["servers"].keys()
    ]
    if overlap:
        print(f"config dict from '{appendPrefix}' overlaps with '{confPrefix}")
        return None
    else:
        confDict["servers"].update(appenDict["servers"])
        # launcher() and Pidd both log through launch.LAUNCH_LOGGER, which only
        # launch.main() populates. Without this, appending died on
        # "AttributeError: 'NoneType' object has no attribute 'info'" before any
        # server was spawned. Assign onto the module so launch's own global is
        # what gets rebound.
        helaodirs = helao_dirs(confDict, "launcher")
        launch.LAUNCH_LOGGER = logging.make_logger(
            __file__,
            log_dir=helaodirs.log_root,
            log_level=confDict.get("log_level", 20),
        )
        # Deliberately NOT calling launch.CONSOLE.activate(): this process exits
        # as soon as the servers are spawned, and piping their output would close
        # the read end on the way out, killing each server on its next console
        # write. Appended servers inherit this terminal instead.
        launcher(confPrefix, confDict, helao_repo_root)


if __name__ == "__main__":
    appender(confPrefix, appendPrefix)
