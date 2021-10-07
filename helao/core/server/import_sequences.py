
__all__ = ["import_sequences"]

import os
import sys
from importlib import import_module

from helao.core.helper import print_message


def import_sequences(
    world_config_dict: dict, library_path: str = None, server_name: str = ""
):
    """Import sequence functions into environment."""
    process_lib = {}
    if library_path is None:
        library_path = world_config_dict.get(
            "process_library_path", os.path.join("helao", "library", "sequence")
        )
    if not os.path.isdir(library_path):
        print_message(
            world_config_dict,
            server_name,
            f" ... library path {library_path} was specified but is not a valid directory",
        )
        return process_lib  # False
    sys.path.append(library_path)
    for actlib in world_config_dict["process_libraries"]:
        tempd = import_module(actlib).__dict__
        process_lib.update({func: tempd[func] for func in tempd["SEQUENCES"]})
    print_message(
        world_config_dict,
        server_name,
        f" ... imported {len(world_config_dict['process_libraries'])} sequences specified by config.",
    )
    return process_lib  # True
