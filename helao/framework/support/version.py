"""Helpers for resolving HELAO version strings and source-file git hashes.

These call out to ``git`` / the filesystem at *call* time only. There is no
module-level side effect: callers invoke the helpers explicitly so importing
this module is pure.
"""

import os
import inspect
import subprocess
from datetime import datetime
from socket import gethostname

__all__ = ["get_hlo_version"]


def get_branch_commithash() -> tuple:
    """Return ``(branch, short_commit_hash)`` of the working tree, or ``("", "")`` on failure."""
    try:
        command = ["git", "rev-parse", "--abbrev-ref", "HEAD"]
        branch = (
            subprocess.check_output(command, stderr=subprocess.STDOUT)
            .decode("utf8")
            .strip()
        )
        command = ["git", "rev-parse", "--short", "HEAD"]
        commit_hash = (
            subprocess.check_output(command, stderr=subprocess.STDOUT)
            .decode("utf8")
            .strip()
        )
        return branch, commit_hash
    except Exception:
        return "", ""


def get_filehash(filename: str) -> str:
    """Return the short git hash of the last commit that touched `filename`, or ``""`` on failure."""
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


def get_hlo_version() -> str:
    """Return the HELAO version string.

    Uses the current short git commit hash when available, falling back to
    ``{hostname}_{YYMMDD}``.
    """
    try:
        return get_branch_commithash()[1]
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
