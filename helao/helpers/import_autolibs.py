"""Dynamic loader for experiment and sequence library modules.

``import_autolibs`` walks the ``experiment_libraries`` or
``sequence_libraries`` entries of a world config, locates each named
``*.py`` under the deployment's library directory (with fallbacks to the
``hte`` deployment and a glob across all deployments), executes it, and
collects the public callables advertised by the module's ``EXPERIMENTS`` or
``SEQUENCES`` list alongside their file hashes and source paths.
"""

__all__ = [
    "import_autolibs",
    "deployment_from_config_path",
    "repo_root",
    "repo_path",
]

import os
from functools import lru_cache
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


@lru_cache(maxsize=1)
def repo_root() -> str:
    """Absolute path of the repo root, derived from the ``helao`` package.

    Every path this module builds used to be resolved against the *working
    directory*, which is only the repo root by luck: the FastAPI and Bokeh
    launchers happen to start there, and the Reflex process does not -- it runs
    from its app directory, where ``helao/deploy/...`` names nothing.
    """
    import helao

    return os.path.dirname(os.path.dirname(os.path.abspath(helao.__file__)))


def repo_path(path: str) -> str:
    """Resolve a repo-relative path against the repo root; absolute paths pass through."""
    if not path:
        return path
    return path if os.path.isabs(path) else os.path.join(repo_root(), path)


def _entry_path(entry: str) -> Optional[str]:
    """Absolute path of a library entry written as a ``.py`` path, or ``None``.

    A config may name a library by module name or by path. A path is tried as
    written first -- an absolute path, or a relative one that happens to match
    the cwd -- then against the repo root, so the same config works from any
    working directory.
    """
    if not entry.endswith(".py"):
        return None
    for candidate in (entry, repo_path(entry)):
        if os.path.isfile(candidate):
            return candidate
    return None


def deployment_from_config_path(config_path: str) -> Optional[str]:
    """Deployment name owning a config, or ``None`` if it lives outside the tree.

    Only a config at ``.../helao/deploy/<deployment>/configs/<name>.yml`` names
    its deployment by position. This used to be read as "two directories up",
    which returns *something* for any path at all: a config copied to
    ``C:\\INST_hlo\\DATA\\USER_CONFIG\\eche10.yml`` yielded the deployment
    ``DATA``, and every library lookup then pointed at
    ``helao/deploy/DATA/experiments``. Anchoring on the literal ``helao/deploy``
    segment makes the out-of-tree case answerable -- ``None`` -- instead of
    confidently wrong.

    Args:
        config_path: Path a config was loaded from.

    Returns:
        The deployment directory name, or ``None`` when the path is not under
        ``helao/deploy/<deployment>/``.
    """
    if not config_path:
        return None
    parts = os.path.normpath(config_path).split(os.sep)
    for index, part in enumerate(parts):
        if (
            part == "deploy"
            and index > 0
            and parts[index - 1] == "helao"
            and index + 1 < len(parts)
        ):
            return parts[index + 1]
    return None


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
        lib_dir: Directory containing the library modules. When omitted it is
            resolved in order from the config's ``<lib_type>_path``, the
            deployment named by the config's own path, and the deployment the
            launcher resolved (``CONFIG['deployment']``). If none of those
            yields a real directory, each library is resolved individually
            against the deployment tree instead.
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
        entry_path = _entry_path(lib_file)
        if entry_path is not None:
            lib_path = entry_path
            # The module name stays the entry as written, so a library keeps
            # the same sys.modules key it had when this only looked in the cwd.
            lib_file = lib_file.split(".py")[0]
        else:
            lib_file = lib_file.split(".py")[0]
            LOGGER.info(
                f"importing {lib_type}s from '{lib_file}' from '{lib_dir}'",
            )
            lib_path = repo_path(os.path.join(lib_dir, f"{lib_file}.py"))
            if not os.path.isfile(lib_path):
                LOGGER.warning(
                    f"{lib_type} library path {lib_path} does not exist, trying 'hte' deployment",
                )
                lib_path = repo_path(
                    os.path.join(
                        "helao", "deploy", "hte", f"{lib_type}s", f"{lib_file}.py"
                    )
                )
            if not os.path.isfile(lib_path):
                lib_paths = glob(
                    repo_path(
                        os.path.join(
                            "helao", "deploy", "*", f"{lib_type}s", f"{lib_file}.py"
                        )
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
        lib_dir = world_config_dict.get(f"{lib_type}_path")
    if lib_dir is None:
        # The config's own path first, then the deployment the launcher
        # resolved. A config launched by full path from outside the repo
        # (e.g. one copied into USER_CONFIG and edited) names no deployment
        # positionally, and only the launcher knows which one its servers
        # came from.
        global_cfg = config_loader.CONFIG or {}
        deployment = deployment_from_config_path(
            world_config_dict.get("loaded_config_path")
            or global_cfg.get("loaded_config_path")
            or ""
        ) or global_cfg.get("deployment")
        if deployment:
            lib_dir = os.path.join("helao", "deploy", deployment, f"{lib_type}s")
    lib_dir = repo_path(lib_dir or "")
    if not lib_dir or not os.path.isdir(lib_dir):
        # Not fatal, and NOT an early return. get_libs already falls back per
        # entry -- 'hte', then a glob across every deployment -- and returning
        # here skipped all of it, handing the orchestrator an empty library and
        # the operator nothing to select. Blanking lib_dir routes each entry
        # straight into that fallback; entries written as explicit .py paths
        # never needed lib_dir at all.
        if lib_dir:
            LOGGER.warning(
                f"{lib_type} path {lib_dir} is not a valid directory; resolving "
                f"each {lib_type} library against the deployment tree instead",
            )
        else:
            LOGGER.warning(
                f"no {lib_type} directory could be resolved for this config "
                f"(it names no deployment and sets no {lib_type}_path); "
                f"resolving each {lib_type} library against the deployment tree",
            )
        lib_dir = ""

    libs = world_config_dict.get(f"{lib_type}_libraries", [])
    for library in libs:
        get_libs(lib_dir=lib_dir, lib_file=library)

    # now add all user_seq
    if user_lib_dir is not None:
        user_lib_dir = repo_path(user_lib_dir)
    if user_lib_dir is not None and not os.path.isdir(user_lib_dir):
        # Previously unreachable when the dir was missing, because the invalid
        # lib_dir check returned first. It no longer does, so an absent user
        # dir would raise from os.listdir instead of being skipped.
        LOGGER.warning(
            f"user {lib_type} path {user_lib_dir!r} is not a valid directory; "
            f"no custom {lib_type}s were imported",
        )
    elif user_lib_dir is not None:
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
