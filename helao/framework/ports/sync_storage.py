"""Sync-storage port: synchronous local-filesystem tree operations.

The data syncer walks a finished RUNS tree (sequence/experiment/action dirs +
their meta/HLO/aux/lock files), reads and writes per-node ``.prg`` progress
docs, and relocates finished nodes into the synced tree (zipping + cleaning up
empty dirs along the way). This port captures exactly that synchronous local
filesystem surface so the domain syncer never touches ``os``/``shutil``/``glob``
directly.

Pure port (Protocols + typing only -- no I/O libraries). The real adapter lives
in ``adapters/fs_sync_storage.py``; the fake in ``adapters/fakes/sync_storage.py``.
"""
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class SyncStorage(Protocol):
    """Synchronous local-filesystem tree inspection and mutation."""

    # --- inspection ---

    def exists(self, path: Path) -> bool:
        """Return ``True`` if ``path`` exists on disk."""
        ...

    def list_pending(
        self, finished_root: Path, kind: str, omit_manual: bool
    ) -> list[Path]:
        """List pending node dirs of ``kind`` under ``finished_root``.

        ``omit_manual`` skips manually-flagged nodes.
        """
        ...

    def list_children(self, parent_dir: Path) -> list[Path]:
        """List child meta files one level down (``*/*.yml``) under ``parent_dir``."""
        ...

    def hlo_files(self, dir_: Path) -> list[Path]:
        """List HLO data files in ``dir_``."""
        ...

    def misc_files(self, dir_: Path, node_type: str) -> list[Path]:
        """List auxiliary (non-meta, non-HLO) files in ``dir_`` for ``node_type``."""
        ...

    def lock_files(self, dir_: Path) -> list[Path]:
        """List lock files in ``dir_``."""
        ...

    def file_size(self, path: Path) -> int:
        """Return the size of ``path`` in bytes."""
        ...

    # --- yml + prg ---

    def read_yml(self, path: Path) -> dict:
        """Read and return the YAML document at ``path``."""
        ...

    def write_yml(self, path: Path, data: dict) -> None:
        """Write ``data`` as YAML at ``path``."""
        ...

    def write_process_meta(self, path: Path, data: dict) -> None:
        """Write a process meta YAML at an absolute ``path``, creating parent dirs.

        Unlike :meth:`write_yml` (which writes into existing run-tree dirs), this
        targets the PROCESSES root outside the RUNS trees, where the parent
        directory may not yet exist.
        """
        ...

    def read_prg(self, path: Path) -> dict:
        """Read and return the ``.prg`` progress doc at ``path`` (``{}`` if missing)."""
        ...

    def write_prg(self, path: Path, data: dict) -> None:
        """Write ``data`` as the ``.prg`` progress doc at ``path``."""
        ...

    def remove_prg(self, path: Path) -> None:
        """Remove the ``.prg`` progress doc at ``path``."""
        ...

    # --- mutation ---

    def move_to_synced(self, path: Path) -> Path:
        """Move ``path`` from the finished tree into the synced tree; return its new path."""
        ...

    def revert_to_finished(self, path: Path) -> Path:
        """Move ``path`` from the synced tree back to the finished tree; return its new path."""
        ...

    def move_tree(self, src: Path, dst: Path) -> Path:
        """Move the directory tree ``src`` to ``dst``; return ``dst``."""
        ...

    def zip_dir(self, path: Path) -> Path:
        """Zip the directory ``path``; return the path of the created archive."""
        ...

    def cleanup_empty(self, path: Path) -> bool:
        """Remove ``path`` if it is an empty directory; return ``True`` if removed."""
        ...

    def remove(self, path: Path) -> None:
        """Remove the file or directory at ``path``."""
        ...
