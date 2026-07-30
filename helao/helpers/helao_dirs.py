"""Resolve and prepare the on-disk directory layout used by a HELAO server.

Given a loaded config, ``helao_dirs`` ensures the standard ``RUNS_ACTIVE``,
``LOGS``, ``STATES``, ``DATABASE``, ``USER_CONFIG``, ``ANALYSES`` and
``PROCESSES`` subdirectories exist under the configured ``root``, archives
any leftover ``*.txt`` log files from a previous run, and returns a
populated ``HelaoDirs`` model.
"""

__all__ = ["helao_dirs"]

import os
import re
import zipfile
from glob import glob
from typing import Optional

from helao.core.models.helaodirs import HelaoDirs
from helao.core.models.run_dir import RunDir

#: Process-level cache keyed on ``(root, server_name)``. Bokeh re-runs each
#: ``makeBokehApp`` per client connection, and ``Vis.__init__`` calls
#: ``helao_dirs`` every time; the resolved layout is identical for a fixed
#: root, so caching avoids redundant directory-existence checks and, more
#: importantly, avoids re-running the old-log archival glob on every session.
#: Non-Bokeh servers call this once at startup, so caching is a no-op for them.
_HELAO_DIRS_CACHE: dict = {}


def helao_dirs(world_cfg: dict, server_name: Optional[str] = None) -> HelaoDirs:
    """Create the standard HELAO directory tree and return its paths.

    If ``world_cfg`` defines a ``root``, the canonical subdirectories under
    that root are created if missing and any prior ``*.txt`` logs under
    ``LOGS/<server_name>`` are zipped and removed. If ``root`` is absent,
    a ``HelaoDirs`` with all-``None`` paths is returned.

    Args:
        world_cfg: Loaded world configuration dictionary.
        server_name: Server name used to locate this server's log directory
            for archival. Logs are only rotated when this is provided.

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
        save_root = os.path.join(root, RunDir.ACTIVE.value)
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

        if server_name is not None:
            # zip and remove old txt logs (start new log for every helao launch)
            old_log_txts = glob(os.path.join(log_root, server_name, "*.txt"))
            nots_counter = 0
            for old_log in old_log_txts:
                print(f"Compressing: {old_log}")
                try:
                    timestamp_found = False
                    timestamp = ""
                    with open(old_log, "r") as f:
                        for line in f:
                            if line.replace("error_[", "[").strip().startswith("["):
                                timestamp_found = True
                                timestamp = re.findall(
                                    "[0-9]{2}:[0-9]{2}:[0-9]{2}", line
                                )[0].replace(":", "")
                                zipname = old_log.replace(".txt", f"{timestamp}.zip")
                                arcname = os.path.basename(old_log).replace(
                                    ".txt", f"{timestamp}.txt"
                                )
                                break
                    if not timestamp_found:
                        while os.path.exists(
                            old_log.replace(".txt", f"__{nots_counter}.zip")
                        ):
                            nots_counter += 1
                        zipname = old_log.replace(".txt", f"__{nots_counter}.zip")
                        arcname = os.path.basename(old_log).replace(
                            ".txt", f"__{nots_counter}.txt"
                        )
                    with zipfile.ZipFile(
                        zipname, "w", compression=zipfile.ZIP_DEFLATED
                    ) as zf:
                        zf.write(old_log, arcname)
                    os.remove(old_log)
                except Exception as e:
                    print(f"Error compressing log: {old_log}, {e}")

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
