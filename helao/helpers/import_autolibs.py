__all__ = ["import_autolibs"]

import os
import time
from typing import Optional
from importlib.machinery import SourceFileLoader
from helao.core.version import get_filehash

from helao.helpers import helao_logging as logging
from helao.helpers import config_loader

CONFIG = config_loader.CONFIG

if logging.LOGGER is None:
    LOGGER = logging.make_logger(__file__)
else:
    LOGGER = logging.LOGGER


def import_autolibs(
    world_config_dict: dict,
    library_path: Optional[str] = None,
    user_library_path: Optional[str] = None,
    library_type: str = "sequence",
):
    """Import automation library functions into environment."""

    library_lib = {}
    library_codehash_lib = {}

    def get_libs(lib_path, lib_file):
        LOGGER.info(
            f"importing {library_type}s from '{lib_file}' from '{lib_path}'",
        )
        lib_path = os.path.join(lib_path, f"{lib_file}.py")
        if not os.path.isfile(lib_path):
            LOGGER.warning(
                f"{library_type} library path {lib_path} does not exist, trying 'hte' deployment",
            )
            lib_path = os.path.join(
                "helao", "deploy", "hte", f"{library_type}s", f"{lib_file}.py"
            )
        tempd = SourceFileLoader(lib_file, lib_path).load_module().__dict__
        library_file_hash = get_filehash(lib_path)
        for func in tempd.get(f"{library_type.upper()}S", []):
            if func in tempd:
                library_lib.update({func: tempd[func]})
                library_codehash_lib.update({func: library_file_hash})
                LOGGER.info(
                    f"added {library_type[:3]} '{func}' to {library_type} library"
                )
            else:
                LOGGER.error(
                    f"!!! Could not find {library_type} function '{func}' in '{lib_file}'",
                )

    if library_path is None:
        config_deployment = os.path.basename(
            os.path.dirname(os.path.dirname(CONFIG["loaded_config_path"]))
        )
        library_path = world_config_dict.get(
            f"{library_type}_path",
            os.path.join("helao", "deploy", config_deployment], f"{library_type}s"),
        )
    if not os.path.isdir(library_path):
        LOGGER.error(
            f"{library_type} path {library_path} was specified but is not a valid directory",
        )
        return library_lib
    libs = world_config_dict.get(f"{library_type}_libraries", [])
    for lib in libs:
        get_libs(lib_path=library_path, lib_file=lib)

    # now add all user_seq
    if user_library_path is not None:
        userfiles = [
            os.path.splitext(userfile)[0]
            for userfile in os.listdir(user_library_path)
            if userfile.endswith(".py")
        ]
        for userfile in userfiles:
            get_libs(lib_path=user_library_path, lib_file=userfile)
            LOGGER.info(
                f"Pausing for 3 seconds to notify: custom {library_type}s were imported from {os.path.join(user_library_path, userfile)}",
            )
            time.sleep(3)

    LOGGER.info(
        f"imported {len(libs)} {library_type}s specified by config.",
    )
    return library_lib, library_codehash_lib
