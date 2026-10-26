"""SHA-256 log records for finalized and rewritten output artefacts (spec §5).

Each file gets one INFO record with ``event``/``kind``/``uuid``/``path``/
``bytes``/``sha256`` (and ``reason`` on a rewrite). ``JsonlSinkHandler`` and
the launcher's collector also write those records to the never-deleted
``artifacts_*`` ledger. Never raises: an unreadable file logs
``artifact_hash_failed`` at WARNING.
"""

import asyncio
import hashlib
import os
import stat
import threading
from pathlib import Path
from typing import Optional

from helao.helpers import helao_logging

__all__ = [
    "log_artifact_hashes",
    "log_artifact_hashes_sync",
    "record_uuid",
    "root_for",
    "use_root_logger",
]

# Most specific owner first: a record also carries its parents' uuids.
_UUID_KEYS = (
    "analysis_uuid",
    "action_uuid",
    "process_uuid",
    "experiment_uuid",
    "sequence_uuid",
)
_FALLBACK = None
_TOOL_ROOT = None  # root found by use_root_logger, for a tool with no CONFIG
_FALLBACK_LOCK = threading.Lock()


def record_uuid(doc: dict) -> Optional[str]:
    """The owning uuid of a record dict (action/experiment/sequence/process/analysis)."""
    for key in _UUID_KEYS:
        if doc.get(key):
            return str(doc[key])
    return None


def _uuid_extra(owner_uuid) -> dict:
    """``{"uuid": ...}``, or nothing when the owner is unknown."""
    return {} if owner_uuid is None else {"uuid": str(owner_uuid)}


_RUN_DIRS = ("RUNS", "DIAG", "ANALYSES")


def root_for(path) -> Optional[str]:
    """The helao root above a rewritten run-tree path, or ``None``.

    The first ancestor with a child directory named ``RUNS``, ``RUNS_*``,
    ``DIAG`` or ``ANALYSES`` that contains ``path``.
    """
    p = os.path.abspath(os.fspath(path))
    parent = os.path.dirname(p)
    while parent != os.path.dirname(parent):
        if os.path.isdir(parent):
            try:
                names = os.listdir(parent)
            except OSError:
                names = []
            for name in names:
                if name in _RUN_DIRS or name.startswith("RUNS_"):
                    top = os.path.join(parent, name) + os.sep
                    # normcase: Windows paths compare case-insensitively
                    if os.path.isdir(top) and os.path.normcase(p + os.sep).startswith(
                        os.path.normcase(top)
                    ):
                        return parent
        parent = os.path.dirname(parent)
    return None


def use_root_logger(path, name: str) -> None:
    """For a CLI tool: ledger beside ``path``'s run tree, not in a temp dir.

    Does nothing when a logger is already installed or no root is found.
    """
    global _TOOL_ROOT
    root = None if helao_logging.LOGGER is not None else root_for(path)
    if root is not None:
        _TOOL_ROOT = root
        helao_logging.LOGGER = helao_logging.make_logger(
            name, log_dir=os.path.join(root, "LOGS")
        )


def _logger(logger):
    global _FALLBACK
    if logger is not None:
        return logger
    if helao_logging.LOGGER is not None:
        return helao_logging.LOGGER
    if _FALLBACK is None:
        with _FALLBACK_LOCK:
            if _FALLBACK is None:
                fallback = helao_logging.make_logger("artifact_hash")
                fallback.warning(
                    "no config root: artefact ledger entries go to a temporary directory"
                )
                _FALLBACK = fallback
    return _FALLBACK


def _root(root):
    if root is not None:
        return root
    from helao.helpers import config_loader

    cfg = config_loader.CONFIG
    return (cfg.get("root") if isinstance(cfg, dict) else None) or _TOOL_ROOT


def _rel(path: str, root) -> str:
    absolute = os.path.abspath(path)
    if root:
        base = os.path.abspath(root)
        try:
            if os.path.commonpath([absolute, base]) == base:
                return Path(os.path.relpath(absolute, base)).as_posix()
        except ValueError:
            pass  # different drives on Windows
    return Path(absolute).as_posix()


def log_artifact_hashes_sync(
    paths,
    *,
    kind: str,
    owner_uuid,
    event: str = "artifact_final",
    reason: Optional[str] = None,
    root: Optional[str] = None,
    logger=None,
) -> None:
    """Hash each file and log one record per file; for non-async callers."""
    log = _logger(logger)
    if paths is None:
        log.warning(
            "artifact_hash_failed: paths is None",
            extra={
                "event": "artifact_hash_failed",
                "kind": kind,
                "reason": "paths is None",
            },
        )
        return
    if isinstance(paths, (str, bytes, os.PathLike)):
        paths = [paths]
    try:
        root = _root(root)
        entries = list(paths)
    except Exception as exc:  # spec §5: never raises into the caller
        log.warning(
            f"artifact_hash_failed: bad arguments: {exc}",
            extra={"event": "artifact_hash_failed", "kind": kind, "reason": str(exc)},
        )
        return
    for path in entries:
        rel = str(path)
        try:
            path = os.fsdecode(path)
            # a tool has no CONFIG: find each file's own root, so its path
            # matches the server-style RUNS/... the ledger keys on
            rel = _rel(path, root or root_for(path))
            if not stat.S_ISREG(os.stat(path).st_mode):
                raise OSError("not a regular file")
            with open(path, "rb") as f:
                digest = hashlib.file_digest(f, "sha256").hexdigest()
                size = os.fstat(f.fileno()).st_size
        except Exception as exc:
            log.warning(
                f"artifact_hash_failed {kind} {rel}: {exc}",
                extra={
                    "event": "artifact_hash_failed",
                    "kind": kind,
                    **_uuid_extra(owner_uuid),
                    "path": rel,
                    "reason": str(exc),
                },
            )
            continue
        log.info(
            f"{event} {kind}",
            extra={
                "event": event,
                "kind": kind,
                **_uuid_extra(owner_uuid),
                "path": rel,
                "bytes": size,
                "sha256": digest,
                "reason": reason,
            },
        )


async def log_artifact_hashes(
    paths,
    *,
    kind: str,
    owner_uuid,
    event: str = "artifact_final",
    reason: Optional[str] = None,
    root: Optional[str] = None,
    logger=None,
) -> None:
    """``log_artifact_hashes_sync`` on a worker thread; awaited by the caller."""
    if paths is not None and not isinstance(paths, (str, bytes, os.PathLike)):
        try:
            paths = list(paths)  # snapshot before leaving the loop thread
        except Exception:
            pass  # the sync function reports it
    await asyncio.to_thread(
        log_artifact_hashes_sync,
        paths,
        kind=kind,
        owner_uuid=owner_uuid,
        event=event,
        reason=reason,
        root=root,
        logger=logger,
    )
