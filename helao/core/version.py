import os
import inspect
import subprocess

__all__ = ["hlo_version", "get_hlo_version"]

# version number, gets written into every exp/prg and hlo file
hlo_version = "2024.04.18"


def get_hlo_version():
    """Return hard-coded HELAO release version."""
    return hlo_version

def get_filehash(filename: str):
    filename = os.path.abspath(filename)
    parent_dir = os.path.dirname(filename)
    command = ['git', 'ls-files', '-s', filename, '--abbrev']
    response = subprocess.check_output(command, cwd=parent_dir).decode('utf8').split()
    if response:
        short_hash = response[1]
    else:
        short_hash = ''
    return short_hash

def get_caller_filehash():
    """Return short git hash and filename of calling frame."""
    caller_frame = inspect.stack()[1]
    caller_filename_full = caller_frame.filename
    short_hash = get_filehash(caller_filename_full)
    return short_hash, caller_filename_full


def get_object_filehash(obj):
    """Return short git hash and source file of object."""
    filename = inspect.getabsfile(obj)
    short_hash = get_filehash(filename)
    return short_hash, filename
