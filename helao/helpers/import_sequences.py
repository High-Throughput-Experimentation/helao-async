__all__ = ["import_sequences"]

import os
from importlib.machinery import SourceFileLoader

from helao.helpers.print_message import print_message


def import_sequences(
    world_config_dict: dict, sequence_path: str = None, server_name: str = "", user_sequence_path: str = None
):
    """Import sequence functions into environment."""

    def get_seqs(seq_path, seq_file):
        print_message(
            world_config_dict,
            server_name,
            f"importing sequences from '{seq_file}' from '{seq_path}'",
        )
        tempd = SourceFileLoader(seq_file, os.path.join(seq_path, f"{seq_file}.py")).load_module().__dict__
        for func in tempd.get("SEQUENCES", []):
            if func in tempd:
                sequence_lib.update({func: tempd[func]})
                print_message(
                    world_config_dict,
                    server_name,
                    f"added seq '{func}' to sequence library",
                )
            else:
                print_message(
                    world_config_dict,
                    server_name,
                    f"!!! Could not find sequence function '{func}' in '{seq_file}'",
                    error=True,
                )

    sequence_lib = {}
    if sequence_path is None:
        sequence_path = world_config_dict.get("sequence_path", os.path.join("helao", "sequences"))
    if not os.path.isdir(sequence_path):
        print_message(
            world_config_dict,
            server_name,
            f"sequence path {sequence_path} was specified but is not a valid directory",
        )
        return sequence_lib
    seqlibs = world_config_dict.get("sequence_libraries", [])
    for seqlib in seqlibs:
        get_seqs(seq_path=sequence_path, seq_file=seqlib)

    # now add all user_seq
    if user_sequence_path is not None:
        files = [os.path.splitext(file)[0] for file in os.listdir(user_sequence_path) if file.endswith(".py")]
        for file in files:
            get_seqs(seq_path=user_sequence_path, seq_file=file)

    print_message(
        world_config_dict,
        server_name,
        f"imported {len(seqlibs)} sequences specified by config.",
    )
    return sequence_lib
