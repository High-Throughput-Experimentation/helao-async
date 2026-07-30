"""Dynamic loader for experiment and sequence library modules.

``import_autolibs`` walks the ``experiment_libraries`` or
``sequence_libraries`` entries of a world config, locates each named
``*.py`` under the deployment's library directory (with fallbacks to the
``hte`` deployment and a glob across all deployments), executes it, and
collects the public callables advertised by the module's ``EXPERIMENTS`` or
``SEQUENCES`` list alongside their file hashes and source paths.
"""

__all__ = ["import_autolibs"]

import os
from glob import glob
from importlib.machinery import SourceFileLoader
from typing import Optional

from helao.core.version import get_filehash
from helao.helpers import config_loader
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Process-level cache of ``import_autolibs`` results. For a fixed world config
#: the imported library dict, per-function file hashes, and source paths are
#: invariant, but Bokeh re-runs each ``makeBokehApp`` (and thus ``RemoteBackend``
#: construction) on every client connection. Without this cache each new operator
#: session re-hashes every library file, re-globs the deployment tree, and
#: re-``os.listdir``s the user lib dir. The imported module objects themselves are
#: already cached by ``sys.modules``; caching here also makes the returned hash
#: match the loaded module for the lifetime of the process.
_AUTOLIB_CACHE: dict = {}


def import_autolibs(
    world_config_dict: dict,
    lib_dir: Optional[str] = None,
    user_lib_dir: Optional[str] = None,
    lib_type: str = "sequence",
) -> tuple:
    """Import experiment or sequence library functions named by a config.

    Each library module is expected to expose an ``EXPERIMENTS`` or
    ``SEQUENCES`` list (named after ``lib_type.upper()``) of function names
    to publish. After loading the configured ``<lib_type>_libraries`` from
    ``lib_dir``, all ``.py`` files in ``user_lib_dir`` (if any) are also
    imported.

    Args:
        world_config_dict: World config; ``<lib_type>_libraries`` lists the
            modules to load, and ``<lib_type>_path`` may override ``lib_dir``.
        lib_dir: Directory containing the library modules. Defaults to the
            deployment's ``<lib_type>s`` folder, derived from
            ``CONFIG['loaded_config_path']``.
        user_lib_dir: Optional additional directory whose ``.py`` files are
            all imported.
        lib_type: ``"sequence"`` or ``"experiment"``.

    Returns:
        A 3-tuple ``(lib, codehash_lib, codepath_lib)``: a dict mapping
        function name to the imported callable, a dict mapping function
        name to source-file hash, and a dict mapping function name to
        forward-slash source path.
    """

    # Cache key spans every input that can change the result: the lib type,
    # the (possibly None) explicit dirs, the configured library list + path
    # override, and the loaded config path that pins the deployment. For a
    # running server all of these are fixed, so repeat sessions hit the cache.
    cache_key = (
        lib_type,
        lib_dir,
        user_lib_dir,
        world_config_dict.get("loaded_config_path"),
        tuple(world_config_dict.get(f"{lib_type}_libraries", [])),
        world_config_dict.get(f"{lib_type}_path"),
    )
    cached = _AUTOLIB_CACHE.get(cache_key)
    if cached is not None:
        lib, codehash_lib, codepath_lib = cached
        return dict(lib), dict(codehash_lib), dict(codepath_lib)

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
            os.path.dirname(os.path.dirname(config_loader.CONFIG["loaded_config_path"]))
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
    _AUTOLIB_CACHE[cache_key] = (dict(lib), dict(codehash_lib), dict(codepath_lib))
    return lib, codehash_lib, codepath_lib
