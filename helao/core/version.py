"""Helpers for resolving HELAO version strings and source-file git hashes."""

import inspect
import os
import subprocess
from datetime import datetime
from functools import lru_cache
from socket import gethostname

__all__ = ["hlo_version", "get_hlo_version"]


@lru_cache(maxsize=None)
def get_branch_commithash(work_tree_path: str = ".") -> tuple:
    """Return ``(branch, short_commit_hash)`` of the working tree, or ``("", "")`` on failure.

    Cached for the life of the process: every ``hlo_version`` model default
    calls this, so an uncached version spawns two ``git rev-parse``
    subprocesses per Action/Experiment/Sample constructed. A batch converter
    that builds ~400 sequences was spending ~4 s per plate here alone. The
    checkout cannot change under a running process in any supported flow --
    the hot-reload watcher restarts the server on a pulled commit, which
    rebuilds the cache.
    """
    try:
        command = ["git", "rev-parse", "--abbrev-ref", "HEAD"]
        branch = (
        subprocess.check_output(command, cwd=work_tree_path, stderr=subprocess.STDOUT)
            .decode("utf8")
            .strip()
        )
        command = ["git", "rev-parse", "--short", "HEAD"]
        commit_hash = (
            subprocess.check_output(command, cwd=work_tree_path, stderr=subprocess.STDOUT)
            .decode("utf8")
            .strip()
        )
        return branch, commit_hash
    except Exception:
        return "", ""


@lru_cache(maxsize=None)
def get_filehash(filename: str) -> str:
    """Return the short git hash of the last commit that touched `filename`, or ``""`` on failure.

    Cached per filename for the same reason as :func:`get_branch_commithash`:
    the ``git log`` subprocess is far more expensive than the lookup, and the
    answer is fixed for the life of the process.
    """
    try:
        filename = os.path.abspath(filename)
        parent_dir = os.path.dirname(filename)
        command = ["git", "log", "-n", "1", "--pretty=format:%h", "--", filename]
        response = (
            subprocess.check_output(command, cwd=parent_dir, stderr=subprocess.STDOUT)
            .decode("utf8")
            .split()
        )
        if response:
            short_hash = response[0]
        else:
            short_hash = ""
        return short_hash
    except Exception:
        return ""


def get_hlo_version(work_tree_path: str = ".") -> str:
    """Return the HELAO version string.

    Uses the current short git commit hash when available, falling back to
    ``{hostname}_{YYMMDD}``.
    """
    try:
        return get_branch_commithash(work_tree_path)[1]
    except Exception:
        return f"{gethostname()}_{datetime.now().strftime('%y%m%d')}"


def get_caller_filehash() -> tuple:
    """Return ``(short_hash, filename)`` for the immediate caller's source file."""
    try:
        caller_frame = inspect.stack()[1]
        caller_filename_full = caller_frame.filename
        short_hash = get_filehash(caller_filename_full)
        return short_hash, caller_filename_full
    except Exception:
        return "", ""


def get_object_filehash(obj) -> tuple:
    """Return ``(short_hash, filename)`` for the source file that defines `obj`."""
    try:
        filename = inspect.getabsfile(obj)
        short_hash = get_filehash(filename)
        return short_hash, filename
    except Exception:
        return "", ""


# version number, gets written into every exp/prg and hlo file
hlo_version = get_hlo_version()
