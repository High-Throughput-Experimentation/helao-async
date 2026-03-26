from fsspec.implementations.http import ex
import os
import inspect
import subprocess
from datetime import datetime
from socket import gethostname

__all__ = ["hlo_version", "get_hlo_version"]


def get_branch_commithash():
    """Return current git branch and commit hash."""
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


def get_filehash(filename: str):
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

def get_hlo_version():
    """Return hard-coded HELAO release version."""
    try:
        return get_branch_commithash()[1]
    except Exception:
        return f"{gethostname()}_{datetime.now().strftime('%y%m%d')}"


def get_caller_filehash():
    """Return short git hash and filename of calling frame."""
    try:
        caller_frame = inspect.stack()[1]
        caller_filename_full = caller_frame.filename
        short_hash = get_filehash(caller_filename_full)
        return short_hash, caller_filename_full
    except Exception:
        return "", ""


def get_object_filehash(obj):
    """Return short git hash and source file of object."""
    try:
        filename = inspect.getabsfile(obj)
        short_hash = get_filehash(filename)
        return short_hash, filename
    except Exception:
        return "", ""


# version number, gets written into every exp/prg and hlo file
hlo_version = get_hlo_version()
