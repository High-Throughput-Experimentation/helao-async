__all__ = ["import_experiments"]

import os
import time
from importlib.machinery import SourceFileLoader
from helao.helpers.print_message import print_message
from helaocore.version import get_filehash

from helao.helpers import logging

if logging.LOGGER is None:
    LOGGER = logging.make_logger(logger_name="import_experiments_standalone")
else:
    LOGGER = logging.LOGGER

def import_experiments(
    world_config_dict: dict,
    experiment_path: str = None,
    server_name: str = "",
    user_experiment_path: str = None,
):
    """Import experiment functions into environment."""

    experiment_lib = {}
    experiment_codehash_lib = {}

    def get_exps(exp_path, exp_file):
        print_message(
            LOGGER,
            server_name,
            f"importing exeriments from '{exp_file}' from '{exp_path}'",
        )
        tempd = (
            SourceFileLoader(exp_file, os.path.join(exp_path, f"{exp_file}.py"))
            .load_module()
            .__dict__
        )
        experiment_file_hash = get_filehash(os.path.join(exp_path, f"{exp_file}.py"))
        for func in tempd.get("EXPERIMENTS", []):
            if func in tempd:
                experiment_lib.update({func: tempd[func]})
                experiment_codehash_lib.update({func: experiment_file_hash})
                print_message(
                    LOGGER,
                    server_name,
                    f"added exp '{func}' to experiment library",
                )
            else:
                print_message(
                    LOGGER,
                    server_name,
                    f"!!! Could not find experiment function '{func}' in '{exp_file}'",
                    error=True,
                )

    if experiment_path is None:
        experiment_path = world_config_dict.get(
            "experiment_path", os.path.join("helao", "experiments")
        )
    if not os.path.isdir(experiment_path):
        print_message(
            LOGGER,
            server_name,
            f"experiment path {experiment_path} was specified but is not a valid directory",
        )
        return experiment_lib  # False
    explibs = world_config_dict.get("experiment_libraries", [])
    for explib in explibs:
        get_exps(exp_path=experiment_path, exp_file=explib)

    # now add all user_exp
    if user_experiment_path is not None:
        userfiles = [
            os.path.splitext(userfile)[0]
            for userfile in os.listdir(user_experiment_path)
            if userfile.endswith(".py")
        ]
        for userfile in userfiles:
            get_exps(exp_path=user_experiment_path, exp_file=userfile)
            print_message(
                LOGGER,
                server_name,
                f"Pausing for 3 seconds to notify: custom experiments were imported from {os.path.join(user_experiment_path, userfile)}",
            )
            time.sleep(3)

    print_message(
        LOGGER,
        server_name,
        f"imported {len(explibs)} experiments specified by config.",
    )
    return experiment_lib, experiment_codehash_lib
