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
from typing import Optional

from helao.helpers import helao_logging

__all__ = ["log_artifact_hashes", "log_artifact_hashes_sync", "record_uuid"]

_UUID_KEYS = (
    "action_uuid",
    "experiment_uuid",
    "sequence_uuid",
    "process_uuid",
    "analysis_uuid",
)
_FALLBACK = None


def record_uuid(doc: dict) -> Optional[str]:
    """The owning uuid of a record dict (action/experiment/sequence/process/analysis)."""
    for key in _UUID_KEYS:
        if doc.get(key):
            return str(doc[key])
    return None


def _logger(logger):
    global _FALLBACK
    if logger is not None:
        return logger
    if helao_logging.LOGGER is not None:
        return helao_logging.LOGGER
    if _FALLBACK is None:
        _FALLBACK = helao_logging.make_logger("artifact_hash")
        _FALLBACK.warning(
            "no config root: artefact ledger entries go to a temporary directory"
        )
    return _FALLBACK


def _root(root):
    if root is not None:
        return root
    from helao.helpers import config_loader

    cfg = config_loader.CONFIG
    return cfg.get("root") if isinstance(cfg, dict) else None


def _rel(path: str, root) -> str:
    absolute = os.path.abspath(path)
    if root:
        base = os.path.abspath(root)
        try:
            if os.path.commonpath([absolute, base]) == base:
                return os.path.relpath(absolute, base)
        except ValueError:
            pass  # different drives on Windows
    return absolute


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
    root = _root(root)
    for path in paths:
        path = os.fspath(path)
        rel = _rel(path, root)
        common = {"kind": kind, "uuid": str(owner_uuid), "path": rel}
        try:
            with open(path, "rb") as f:
                digest = hashlib.file_digest(f, "sha256").hexdigest()
            size = os.path.getsize(path)
        except OSError as exc:
            log.warning(
                f"artifact_hash_failed {kind} {rel}: {exc}",
                extra={**common, "event": "artifact_hash_failed", "reason": str(exc)},
            )
            continue
        log.info(
            f"{event} {kind} {rel} sha256={digest}",
            extra={
                **common,
                "event": event,
                "bytes": size,
                "sha256": digest,
                "reason": reason,
            },
        )


async def log_artifact_hashes(paths, **kwargs) -> None:
    """``log_artifact_hashes_sync`` on a worker thread; awaited by the caller."""
    await asyncio.to_thread(log_artifact_hashes_sync, list(paths), **kwargs)
