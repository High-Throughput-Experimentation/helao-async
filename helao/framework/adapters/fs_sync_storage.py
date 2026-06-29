"""Filesystem sync-storage adapter: real-disk implementation of ``SyncStorage``.

Realizes :class:`helao.framework.ports.sync_storage.SyncStorage` against the
local filesystem, byte-compatible with the legacy data syncer
(``helao.core.drivers.data.sync_driver``). Each method maps directly onto a
legacy ``HelaoYml`` property, ``Progress`` method, or module function; cited
inline so the on-disk results stay identical to historical data and the live
``HelaoSyncer``.

Lives under ``adapters/`` so it may import I/O libraries (``os``, ``shutil``,
``glob``, ``zipfile`` via ``helao.helpers.file_utils``). It reuses the pure path
math in :mod:`helao.framework.domain.sync.paths` rather than duplicating it, and
the YAML helpers in :mod:`helao.framework.support.yml_tools` for byte-compatible
serialization (2/4/2 indent, ``null`` for None, duplicate keys allowed).

Adapters must NOT be imported by the domain layer.
"""
from __future__ import annotations

import os
import shutil
from glob import glob
from pathlib import Path

from helao.framework.domain.sync import paths as syncpaths
from helao.framework.ports.sync_storage import SyncStorage
from helao.framework.support.yml_tools import yml_dumps, yml_load
from helao.helpers.file_utils import zip_dir as _zip_dir_helper

# Glob depth (number of intermediate "*" dir levels) below RUNS_FINISHED for
# each pending node kind. Matches legacy list_pending/_acts/_exps globs:
#   seq: <finished>/*/*/*/*-seq.yml          (week/date/seq)
#   exp: <finished>/*/*/*/*/*-exp.yml        (week/date/seq/exp)
#   act: <finished>/*/*/*/*/*/*-act.yml      (week/date/seq/exp/act)
_PENDING_GLOB = {
    "seq": ("*", "*", "*", "*-seq.yml"),
    "exp": ("*", "*", "*", "*", "*-exp.yml"),
    "act": ("*", "*", "*", "*", "*", "*-act.yml"),
}

_MANUAL_MARKER = "manual_orch_seq"


class FsSyncStorage(SyncStorage):
    """``SyncStorage`` backed by the real local filesystem.

    Stateless: every method operates on absolute ``Path`` arguments supplied by
    the app pipeline. No roots are baked in -- the app injects fully-resolved
    paths (computed via :mod:`helao.framework.domain.sync.paths`).
    """

    # --- inspection ---

    def exists(self, path: Path) -> bool:
        """Return ``True`` if ``path`` exists. Legacy ``Path.exists()``."""
        return Path(path).exists()

    def list_pending(
        self, finished_root: Path, kind: str, omit_manual: bool
    ) -> list[Path]:
        """List pending ``kind`` node ymls under ``finished_root``.

        Legacy ``list_pending`` / ``list_pending_acts`` / ``list_pending_exps``
        (sync_driver.py 1656-1708). ``kind`` selects the glob depth + filename
        suffix; ``omit_manual`` drops paths containing ``manual_orch_seq``.
        """
        try:
            pattern_parts = _PENDING_GLOB[kind]
        except KeyError as exc:
            raise ValueError(
                f"unknown pending kind {kind!r}; expected one of {sorted(_PENDING_GLOB)}"
            ) from exc
        pattern = os.path.join(str(finished_root), *pattern_parts)
        pending = glob(pattern)
        if omit_manual:
            pending = [x for x in pending if _MANUAL_MARKER not in x]
        return [Path(x) for x in pending]

    def list_children(self, parent_dir: Path) -> list[Path]:
        """List child meta ymls one level down, sorted oldest-first.

        Legacy ``HelaoYml.list_children`` (sync_driver.py 394-406):
        ``glob("*/*.yml")`` one level below ``parent_dir``, sorted by the
        record timestamp parsed from each filename (``paths.node_timestamp``).
        """
        children = list(Path(parent_dir).glob("*/*.yml"))
        return sorted(children, key=lambda p: syncpaths.node_timestamp(p.name))

    def hlo_files(self, dir_: Path) -> list[Path]:
        """``.hlo`` files in ``dir_`` (shallow). Legacy ``HelaoYml.hlo_files``."""
        return [
            x for x in Path(dir_).glob("*") if x.is_file() and x.suffix == ".hlo"
        ]

    def misc_files(self, dir_: Path, node_type: str) -> list[Path]:
        """Auxiliary (non-yml/hlo/lock) files in ``dir_``.

        Legacy ``HelaoYml.misc_files`` (sync_driver.py 432-455): actions recurse
        (``rglob``); experiments and sequences are shallow (``glob``). ``.yml``,
        ``.hlo`` and ``.lock`` files are excluded. ``node_type`` may be the
        abbreviation (``act``/``exp``/``seq``) or the expanded name.
        """
        is_action = node_type in ("act", "action")
        base = Path(dir_)
        entries = base.rglob("*") if is_action else base.glob("*")
        return [
            x
            for x in entries
            if x.is_file()
            and x.suffix != ".yml"
            and x.suffix != ".hlo"
            and x.suffix != ".lock"
        ]

    def lock_files(self, dir_: Path) -> list[Path]:
        """``.lock`` files in ``dir_`` (shallow). Legacy ``HelaoYml.lock_files``."""
        return [
            x for x in Path(dir_).glob("*") if x.is_file() and x.suffix == ".lock"
        ]

    def file_size(self, path: Path) -> int:
        """Size of ``path`` in bytes. Legacy ``path.stat().st_size``."""
        return Path(path).stat().st_size

    # --- yml + prg ---

    def read_yml(self, path: Path) -> dict:
        """Load the YAML document at ``path``. Legacy ``HelaoYml.meta`` (yml_load)."""
        return yml_load(Path(path))

    def write_yml(self, path: Path, data: dict) -> None:
        """Write ``data`` as UTF-8 YAML at ``path``.

        Legacy ``HelaoYml.write_meta`` (sync_driver.py 494-506):
        ``target.write_text(str(yml_dumps(meta_dict)), encoding="utf-8")``.
        """
        Path(path).write_text(str(yml_dumps(data)), encoding="utf-8")

    def write_process_meta(self, path: Path, data: dict) -> None:
        """Write a process meta YAML at ``path``, creating parent dirs first.

        Mirrors legacy ``sync_process`` (sync_driver.py 1559-1561):
        ``os.makedirs(save_dir, exist_ok=True)`` then write ``yml_dumps(model)``.
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(yml_dumps(data)), encoding="utf-8")

    def read_prg(self, path: Path) -> dict:
        """Read the ``.prg`` progress doc at ``path``; ``{}`` if missing.

        Legacy ``Progress.read_dict`` is ``yml_load(self.prg)``; the port
        contract additionally specifies ``{}`` when the file is absent.
        """
        p = Path(path)
        if not p.exists():
            return {}
        return yml_load(p)

    def write_prg(self, path: Path, data: dict) -> None:
        """Write ``data`` as the ``.prg`` doc, creating parents.

        Legacy ``Progress.write_dict``:
        ``prg.write_text(str(yml_dumps(out_dict)), encoding="utf-8")`` (the
        legacy ``__init__`` mkdir's the parent before the first write).
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(yml_dumps(data)), encoding="utf-8")

    def remove_prg(self, path: Path) -> None:
        """Remove the ``.prg`` doc. Legacy ``Progress.remove_prg`` (``unlink``).

        Tolerant of a missing file (``missing_ok=True``) so reset/retry paths
        are idempotent.
        """
        Path(path).unlink(missing_ok=True)

    # --- mutation ---

    def move_to_synced(self, path: Path) -> Path:
        """Move ``path`` FINISHED->SYNCED; return the destination.

        Legacy ``move_to_synced`` (sync_driver.py 97-126). Path math delegates
        to ``paths.compute_synced_path``. Mirrors legacy no-op semantics:
        already-synced or missing source returns the (would-be) target path
        without moving; an existing FINISHED source is ``shutil.move``'d after
        its parent is created. The port's ``-> Path`` signature means we always
        return the destination ``Path`` (legacy returned the target for the
        no-op cases too).
        """
        src = Path(path)
        target = Path(syncpaths.compute_synced_path(src))
        if "RUNS_SYNCED" in src.parts:
            return target
        if not src.exists():
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(target))
        return target

    def revert_to_finished(self, path: Path) -> Path:
        """Move ``path`` SYNCED->FINISHED; return the destination.

        Legacy ``revert_to_finished`` (sync_driver.py 129-151). Path math
        delegates to ``paths.compute_finished_path`` (raises ``ValueError`` if
        ``RUNS_SYNCED`` is absent, matching legacy ``parts.index``).
        """
        src = Path(path)
        target = Path(syncpaths.compute_finished_path(src))
        target.parent.mkdir(parents=True, exist_ok=True)
        return src.replace(target)

    def move_tree(self, src: Path, dst: Path) -> Path:
        """Move the directory tree ``src`` to ``dst``, creating ``dst`` parents."""
        dst = Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(Path(src)), str(dst))
        return dst

    def zip_dir(self, path: Path) -> Path:
        """Zip directory ``path`` into a sibling ``<name>.zip``; return its path.

        Legacy zips a synced sequence dir as ``parent.parent/<name>.zip`` and
        deletes the source (``app/sync_driver`` line 1304-1312 via
        ``helao.helpers.file_utils.zip_dir``). ``.lock`` files are skipped and
        the source tree is removed on success.
        """
        src = Path(path)
        archive = src.parent.joinpath(f"{src.name}.zip")
        _zip_dir_helper(src, archive)
        return archive

    def cleanup_empty(self, path: Path) -> bool:
        """Recursively rmdir ``path`` if its subtree is empty; return success.

        Legacy ``try_remove_empty`` (sync_driver.py 740-773): an empty dir is
        removed; otherwise recurse into subdirs and report success only when no
        files remain and every subdir was removed.
        """
        target = str(path)
        contents = glob(os.path.join(target, "*"))
        if len(contents) == 0:
            try:
                os.rmdir(target)
                return True
            except OSError:
                return False
        sub_dirs = [x for x in contents if os.path.isdir(x)]
        sub_removes = [self.cleanup_empty(Path(d)) for d in sub_dirs]
        sub_success = all(sub_removes)
        sub_files = [x for x in contents if os.path.isfile(x)]
        return bool(not sub_files and sub_success)

    def remove(self, path: Path) -> None:
        """Remove the file at ``path``. Legacy ``path.unlink()``."""
        Path(path).unlink()
