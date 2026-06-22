"""Deterministic source-code hashing for sequence/experiment versioning.

The legacy implementation (``helao/core/version.py`` ``get_filehash`` and
``helao/helpers/import_autolibs.py``) tagged each library function with the
*git* short-hash of the file that defined it. That approach requires a git
checkout, shells out to ``git``, and is not reproducible outside the repo.

This module provides a pure, stdlib-only replacement: a stable content hash
of a python source string (:func:`code_hash`), of a file's contents
(:func:`file_hash`), or of the source defining a Python object
(:func:`object_hash`). Same input always yields the same hash, with no
network, subprocess, or git dependency.
"""

__all__ = ["code_hash", "file_hash", "object_hash"]

import hashlib
import inspect
from pathlib import Path
from typing import Union

# Default truncation length for the hex digest. Mirrors the brevity of the
# git short-hash the legacy code stored, while remaining collision-resistant
# enough for code-version tagging.
DEFAULT_LENGTH = 12


def code_hash(source: str, length: int = DEFAULT_LENGTH) -> str:
    """Return a deterministic hex hash of a python source string.

    Args:
        source: Source text to hash.
        length: Number of leading hex characters to return.

    Returns:
        The truncated lowercase hex SHA-256 digest of ``source``.
    """
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return digest[:length]


def file_hash(filename: Union[str, Path], length: int = DEFAULT_LENGTH) -> str:
    """Return the :func:`code_hash` of a file's contents, or ``""`` on failure.

    Args:
        filename: Path to the source file.
        length: Number of leading hex characters to return.

    Returns:
        The truncated content hash, or an empty string if the file cannot be
        read.
    """
    try:
        text = Path(filename).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    return code_hash(text, length=length)


def object_hash(obj, length: int = DEFAULT_LENGTH) -> str:
    """Return the :func:`code_hash` of the source defining ``obj``.

    Args:
        obj: Any object whose defining source can be retrieved via
            :func:`inspect.getsource`.
        length: Number of leading hex characters to return.

    Returns:
        The truncated source hash, or an empty string if the source cannot be
        retrieved (e.g. builtins, C extensions).
    """
    try:
        source = inspect.getsource(obj)
    except (OSError, TypeError):
        return ""
    return code_hash(source, length=length)
