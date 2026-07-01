"""Filesystem Storage adapter: real aiofiles-based HLO + meta writer.

Realizes the extended ``Storage`` Protocol with byte-identical HLO output to
legacy ``helao.core.servers.base``::

    [HEADER]\\n%%\\n[JSON ROW]\\n[JSON ROW]\\n...

Meta files (``.act``/``.exp``/``.seq`` YAML) are written atomically via a
unique temp file in the same directory followed by ``os.replace`` so readers
never observe a torn file (mirrors ``Base._write_meta_atomic``). Relocation
copies an auxiliary file (mirrors ``Active.relocate_files`` / ``async_copy``).

Lives under ``adapters/`` so it may import I/O libraries (aiofiles, os,
ruamel.yaml). The YAML formatting matches ``helao.helpers.yml_tools.yml_dumps``
(2/4/2 indent, ``null`` for None, duplicate keys allowed) for meta-byte parity.
"""
import asyncio
import json
import os
from io import StringIO
from typing import Any, Mapping, Sequence
from uuid import uuid1

import aiofiles
import aiofiles.os
import aioshutil
import ruamel.yaml

from helao.framework.ports.storage import Storage, StorageKeyError


async def _retry_busy(thunk, *, attempts: int = 10, delay: float = 0.2):
    """Run an async filesystem op, retrying transient Windows busy-file locks.

    A just-closed ``.hlo`` can stay briefly locked by the OS (a lagging handle
    release, AV/indexer, or a post-processor read), so a single
    ``remove``/``rmtree``/``move`` during RUNS_ACTIVE->FINISHED promotion can
    raise ``PermissionError`` (WinError 32). Retry a bounded number of times
    with a short sleep, then re-raise. ``FileNotFoundError`` is tolerated
    (the target was already moved by a concurrent op). Ports the busy-file
    retry the legacy ``move_dir`` performed.
    """
    for attempt in range(attempts):
        try:
            return await thunk()
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(delay)


def _yml_dumps(obj: Any) -> str:
    """Serialize ``obj`` to YAML using HELAO conventions (2/4/2, null, dup keys)."""
    yaml = ruamel.yaml.YAML(typ="rt")
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.allow_duplicate_keys = True

    def _represent_none(self, data):
        return self.represent_scalar("tag:yaml.org,2002:null", "null")

    yaml.representer.add_representer(type(None), _represent_none)
    buf = StringIO()
    yaml.dump(obj, buf)
    return buf.getvalue()


class _FsHloHandle:
    """Handle wrapping an open aiofiles file object for one HLO connection."""

    def __init__(self, relpath: str, file: Any) -> None:
        self.relpath = relpath
        self.file = file


class FsStorage(Storage):
    """Storage backed by a filesystem rooted at ``save_root``.

    All relpaths are resolved beneath ``save_root``. Parent directories are
    created on demand.
    """

    def __init__(self, save_root: str) -> None:
        self.save_root = save_root

    def _abs(self, relpath: str) -> str:
        return os.path.join(self.save_root, relpath)

    # --- plain JSON docs ---

    def write_json(self, relpath: str, payload: Mapping[str, Any]) -> str:
        path = self._abs(relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dict(payload), f)
        return relpath

    def read_json(self, relpath: str) -> Mapping[str, Any]:
        path = self._abs(relpath)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError as exc:
            raise StorageKeyError(relpath) from exc

    # --- streaming HLO ---

    async def open_hlo(self, relpath: str, header: str) -> _FsHloHandle:
        path = self._abs(relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        f = await aiofiles.open(path, mode="a+")
        if header:
            if not header.endswith("\n"):
                header += "\n"
            await f.write(header)
        # HLO header/data separator, written before the first data row.
        await f.write("%%\n")
        return _FsHloHandle(relpath, f)

    def serialize_hlo_header(self, header: Mapping[str, Any]) -> str:
        # legacy parity: yml_dumps(clean_dict); an empty header renders to "".
        if not header:
            return ""
        return _yml_dumps(dict(header))

    async def append_hlo(self, handle: _FsHloHandle, row: str) -> None:
        if not row.endswith("\n"):
            row += "\n"
        await handle.file.write(row)

    async def close_hlo(self, handle: _FsHloHandle) -> None:
        await handle.file.close()

    # --- atomic meta ---

    async def write_meta(self, relpath: str, doc: Mapping[str, Any]) -> str:
        output_file = self._abs(relpath)
        output_str = _yml_dumps(dict(doc))
        if not output_str.endswith("\n"):
            output_str += "\n"
        output_path = os.path.dirname(output_file)
        os.makedirs(output_path, exist_ok=True)
        tmp_file = os.path.join(
            output_path,
            f".{os.path.basename(output_file)}.{uuid1().hex}.tmp",
        )
        async with aiofiles.open(tmp_file, mode="w") as f:
            await f.write(output_str)
        os.replace(tmp_file, output_file)
        return relpath

    # --- relocate aux file ---

    async def relocate(self, src: str, dst: str) -> str:
        dst_path = self._abs(dst)
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        if src != dst_path:
            await aioshutil.copy(src, dst_path)
        return dst

    async def promote_run_dir(
        self,
        out_dir_relpath: str,
        *,
        manual: bool,
        sync_data: bool,
        recursive: bool,
    ) -> None:
        """File-granular promotion of a run dir out of ``RUNS_ACTIVE``.

        Faithful port of ``helao.helpers.yml_tools.move_dir`` (relative to
        ``save_root``): source is ``RUNS_ACTIVE/<out_dir_relpath>``; each file's
        destination keeps its relpath with ``RUNS_ACTIVE`` rewritten to
        ``RUNS_NOSYNC`` (``.hlo`` and ``not sync_data``) or to the destination
        base (``RUNS_DIAG`` if ``manual`` else ``RUNS_FINISHED``). Non-NOSYNC
        files are copied, NOSYNC files are moved; sources are then removed and
        the emptied source dir is ``rmtree``'d. Missing/already-moved files are
        tolerated and any failure is logged and swallowed.
        """
        from helao.framework.support import helao_logging as _logging

        log = _logging.LOGGER if _logging.LOGGER is not None else None
        try:
            src_dir = self._abs(os.path.join("RUNS_ACTIVE", out_dir_relpath))
            if not os.path.isdir(src_dir):
                return  # nothing written (e.g. save_data off) -> tolerant no-op

            dest_base = "RUNS_DIAG" if manual else "RUNS_FINISHED"

            # enumerate source files (recursive for actions, immediate for exp/seq)
            src_files: list[str] = []
            if recursive:
                for cur, _dirs, files in os.walk(src_dir):
                    for fn in files:
                        src_files.append(os.path.join(cur, fn))
            else:
                for name in os.listdir(src_dir):
                    p = os.path.join(src_dir, name)
                    if os.path.isfile(p):
                        src_files.append(p)

            moved_or_copied: list[str] = []
            for src in src_files:
                if not os.path.isfile(src):
                    continue  # already moved by a concurrent op -> tolerate
                # build dest by rewriting the RUNS_ACTIVE segment of the relpath
                rel = os.path.relpath(src, self.save_root)
                target_root = (
                    "RUNS_NOSYNC"
                    if (src.endswith(".hlo") and not sync_data)
                    else dest_base
                )
                dst = self._abs(
                    rel.replace("RUNS_ACTIVE", target_root, 1)
                )
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if target_root == "RUNS_NOSYNC":
                    await _retry_busy(lambda s=src, d=dst: aioshutil.move(s, d))
                else:
                    await aioshutil.copy(src, dst)
                moved_or_copied.append(src)

            # remove the copied sources (moved NOSYNC files are already gone).
            # Retry transient Windows busy-file locks on the just-closed .hlo.
            for src in moved_or_copied:
                if os.path.isfile(src):
                    await _retry_busy(lambda s=src: aiofiles.os.remove(s))

            # rmtree the (now-empty) source dir; tolerate concurrent removal.
            # For non-recursive promotes the source dir may still hold child
            # subdirs (not yet promoted) -- only remove when it is empty.
            if os.path.isdir(src_dir):
                if recursive or not os.listdir(src_dir):
                    await _retry_busy(lambda d=src_dir: aioshutil.rmtree(d))
        except Exception:
            if log is not None:
                log.error(
                    f"promote_run_dir failed for {out_dir_relpath!r}", exc_info=True
                )

    # --- post-processor ---

    async def run_postprocessor(
        self, name: str, relpath: str, context: Mapping[str, Any]
    ) -> Sequence[Any]:
        # SP4 has no registered processors; the contract returns the file list
        # unchanged. Real processor dispatch is wired in app/ composition.
        return list(context.get("files", []))
