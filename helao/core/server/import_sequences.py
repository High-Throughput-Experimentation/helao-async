
__all__ = ["import_sequences"]

import os
import sys
from importlib import import_module

from helao.core.helper import print_message


def import_sequences(
    world_config_dict: dict, sequence_path: str = None, server_name: str = ""
):
    """Import sequence functions into environment."""
    process_lib = {}
    if sequence_path is None:
        sequence_path = world_config_dict.get(
            "process_sequence_path", os.path.join("helao", "config", "sequence")
        )
    if not os.path.isdir(sequence_path):
        print_message(
            world_config_dict,
            server_name,
            f" ... sequence path {sequence_path} was specified but is not a valid directory",
        )
        return process_lib  # False
    sys.path.append(sequence_path)
    for actlib in world_config_dict["process_libraries"]:
        tempd = import_module(actlib).__dict__
        process_lib.update({func: tempd[func] for func in tempd["SEQUENCES"]})
    print_message(
        world_config_dict,
        server_name,
        f" ... imported {len(world_config_dict['process_libraries'])} sequences specified by config.",
    )
    return process_lib  # True
