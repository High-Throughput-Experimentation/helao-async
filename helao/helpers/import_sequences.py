__all__ = ["import_sequences"]

import os
import time
from importlib.machinery import SourceFileLoader

from helao.helpers.print_message import print_message
from helao.core.version import get_filehash

from helao.helpers import logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER

def import_sequences(
    world_config_dict: dict,
    sequence_path: str = None,
    server_name: str = "",
    user_sequence_path: str = None,
):
    """Import sequence functions into environment."""

    sequence_lib = {}
    sequence_codehash_lib = {}

    def get_seqs(seq_path, seq_file):
        print_message(
            LOGGER,
            server_name,
            f"importing sequences from '{seq_file}' from '{seq_path}'",
        )
        tempd = (
            SourceFileLoader(seq_file, os.path.join(seq_path, f"{seq_file}.py"))
            .load_module()
            .__dict__
        )
        sequence_file_hash = get_filehash(os.path.join(seq_path, f"{seq_file}.py"))
        for func in tempd.get("SEQUENCES", []):
            if func in tempd:
                sequence_lib.update({func: tempd[func]})
                sequence_codehash_lib.update({func: sequence_file_hash})
                print_message(
                    LOGGER,
                    server_name,
                    f"added seq '{func}' to sequence library",
                )
            else:
                print_message(
                    LOGGER,
                    server_name,
                    f"!!! Could not find sequence function '{func}' in '{seq_file}'",
                    error=True,
                )

    if sequence_path is None:
        sequence_path = world_config_dict.get(
            "sequence_path", os.path.join("helao", "sequences")
        )
    if not os.path.isdir(sequence_path):
        print_message(
            LOGGER,
            server_name,
            f"sequence path {sequence_path} was specified but is not a valid directory",
        )
        return sequence_lib
    seqlibs = world_config_dict.get("sequence_libraries", [])
    for seqlib in seqlibs:
        get_seqs(seq_path=sequence_path, seq_file=seqlib)

    # now add all user_seq
    if user_sequence_path is not None:
        userfiles = [
            os.path.splitext(userfile)[0]
            for userfile in os.listdir(user_sequence_path)
            if userfile.endswith(".py")
        ]
        for userfile in userfiles:
            get_seqs(seq_path=user_sequence_path, seq_file=userfile)
            print_message(
                LOGGER,
                server_name,
                f"Pausing for 3 seconds to notify: custom sequences were imported from {os.path.join(user_sequence_path, userfile)}",
            )
            time.sleep(3)

    print_message(
        LOGGER,
        server_name,
        f"imported {len(seqlibs)} sequences specified by config.",
    )
    return sequence_lib, sequence_codehash_lib
