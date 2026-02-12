__all__ = ["import_autolibs"]

import os
from glob import glob
from typing import Optional
from importlib.machinery import SourceFileLoader
from helao.core.version import get_filehash

from helao.helpers import helao_logging as logging
from helao.helpers import config_loader

CONFIG = config_loader.CONFIG
LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


def import_autolibs(
    world_config_dict: dict,
    lib_dir: Optional[str] = None,
    user_lib_dir: Optional[str] = None,
    lib_type: str = "sequence",
):
    """Import automation library functions into environment."""

    lib = {}
    codehash_lib = {}
    codepath_lib = {}

    def get_libs(lib_dir, lib_file):
        if lib_file.endswith(".py") and os.path.isfile(lib_file):
            lib_path = lib_file
            lib_file = lib_file.split(".py")[0]
        else:
            lib_file = lib_file.split(".py")[0]
            LOGGER.info(
                f"importing {lib_type}s from '{lib_file}' from '{lib_dir}'",
            )
            lib_path = os.path.join(lib_dir, f"{lib_file}.py")
            if not os.path.isfile(lib_path):
                LOGGER.warning(
                    f"{lib_type} library path {lib_path} does not exist, trying 'hte' deployment",
                )
                lib_path = os.path.join(
                    "helao", "deploy", "hte", f"{lib_type}s", f"{lib_file}.py"
                )
            if not os.path.isfile(lib_path):
                lib_paths = glob(
                    os.path.join(
                        "helao", "deploy", "*", f"{lib_type}s", f"{lib_file}.py"
                    )
                )
                if lib_paths:
                    lib_path = lib_paths[0]
                    LOGGER.warning(
                        f"found {lib_type} library path {lib_path} in local deployments, using this path"
                    )
                else:
                    raise FileNotFoundError(
                        f"{lib_type} library path {lib_path} does not exist, and no local deployments contain {lib_file}.py in their {lib_type}s folder. Please check your config and file paths."
                    )
        lib_file_hash = get_filehash(lib_path)
        tempd = SourceFileLoader(lib_file, lib_path).load_module().__dict__
        for func in tempd.get(f"{lib_type.upper()}S", []):
            if func in tempd:
                lib.update({func: tempd[func]})
                codehash_lib.update({func: lib_file_hash})
                codepath_lib.update({func: "/".join(lib_path.split(os.sep))})
                LOGGER.info(f"added {lib_type[:3]} '{func}' to {lib_type} library")
            else:
                LOGGER.error(
                    f"!!! Could not find {lib_type} function '{func}' in '{lib_file}'",
                )

    if lib_dir is None:
        config_deployment = os.path.basename(
            os.path.dirname(os.path.dirname(CONFIG["loaded_config_path"]))
        )
        lib_dir = world_config_dict.get(
            f"{lib_type}_path",
            os.path.join("helao", "deploy", config_deployment, f"{lib_type}s"),
        )
    if not os.path.isdir(lib_dir):
        LOGGER.error(
            f"{lib_type} path {lib_dir} was specified but is not a valid directory",
        )
        return lib, codehash_lib, codepath_lib

    libs = world_config_dict.get(f"{lib_type}_libraries", [])
    for library in libs:
        get_libs(lib_dir=lib_dir, lib_file=library)

    # now add all user_seq
    if user_lib_dir is not None:
        userfiles = [
            os.path.splitext(userfile)[0]
            for userfile in os.listdir(user_lib_dir)
            if userfile.endswith(".py")
        ]
        for userfile in userfiles:
            get_libs(lib_dir=user_lib_dir, lib_file=userfile)
            LOGGER.info(
                f"Custom {lib_type}s were imported from {os.path.join(user_lib_dir, userfile)}",
            )

    LOGGER.info(
        f"imported {len(libs)} {lib_type}s specified by config.",
    )
    return lib, codehash_lib, codepath_lib
