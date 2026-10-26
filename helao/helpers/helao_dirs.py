"""Resolve and prepare the on-disk directory layout used by a HELAO server.

Given a loaded config, ``helao_dirs`` ensures the standard ``RUNS``,
``DIAG``, ``LOGS``, ``STATES``, ``DATABASE``, ``USER_CONFIG``, ``ANALYSES``
and ``PROCESSES`` subdirectories exist under the configured ``root``, archives
any leftover ``*.txt`` log files from a previous run, and returns a
populated ``HelaoDirs`` model.
"""

__all__ = ["helao_dirs"]

import os
from typing import Optional

from helao.core.models.helaodirs import HelaoDirs
from helao.core.models.run_dir import diag_root, run_root

#: Process-level cache keyed on ``(root, server_name)``. Bokeh re-runs each
#: ``makeBokehApp`` per client connection, and ``Vis.__init__`` calls
#: ``helao_dirs`` every time; the resolved layout is identical for a fixed
#: root, so caching avoids redundant directory-existence checks.
#: Non-Bokeh servers call this once at startup, so caching is a no-op for them.
_HELAO_DIRS_CACHE: dict = {}


def helao_dirs(world_cfg: dict, server_name: Optional[str] = None) -> HelaoDirs:
    """Create the standard HELAO directory tree and return its paths.

    If ``world_cfg`` defines a ``root``, the canonical subdirectories under
    that root are created if missing. If ``root`` is absent,
    a ``HelaoDirs`` with all-``None`` paths is returned.

    Args:
        world_cfg: Loaded world configuration dictionary.
        server_name: Part of the cache key; the layout does not depend on it.

    Returns:
        A ``HelaoDirs`` model populated with the resolved paths (or all
        ``None`` when ``root`` is absent from the config).
    """

    cache_key = (world_cfg.get("root"), server_name)
    cached = _HELAO_DIRS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    def check_dir(path):
        if not os.path.isdir(path):
            print(
                f"Warning: directory '{path}' does not exist. Creating it.",
            )
            os.makedirs(path)

    if "root" in world_cfg:
        root = world_cfg["root"]
        save_root = str(run_root(root))
        diag_dir = str(diag_root(root))
        log_root = os.path.join(root, "LOGS")
        states_root = os.path.join(root, "STATES")
        db_root = os.path.join(root, "DATABASE")
        user_exp = os.path.join(root, "USER_CONFIG", "EXP")
        user_seq = os.path.join(root, "USER_CONFIG", "SEQ")
        ana_root = os.path.join(root, "ANALYSES")
        process_root = os.path.join(root, "PROCESSES")
        print(f"Found root directory in config: {world_cfg['root']}")
        check_dir(root)
        check_dir(save_root)
        check_dir(diag_dir)
        check_dir(log_root)
        check_dir(states_root)
        check_dir(db_root)
        check_dir(user_exp)
        check_dir(user_seq)
        check_dir(ana_root)
        check_dir(process_root)

        helaodirs = HelaoDirs(
            root=root,
            save_root=save_root,
            log_root=log_root,
            states_root=states_root,
            db_root=db_root,
            user_exp=user_exp,
            user_seq=user_seq,
            ana_root=ana_root,
            process_root=process_root,
        )

    else:
        helaodirs = HelaoDirs(
            root=None,
            save_root=None,
            log_root=None,
            states_root=None,
            db_root=None,
            user_exp=None,
            user_seq=None,
            ana_root=None,
            process_root=None,
        )

    _HELAO_DIRS_CACHE[cache_key] = helaodirs
    return helaodirs
