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
import json
import os
from glob import glob
from io import StringIO
from typing import Any, Mapping, Optional, Sequence
from uuid import uuid1

import aiofiles
import aiofiles.os
import aioshutil
import ruamel.yaml

from helao.framework.ports.storage import Storage, StorageKeyError


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

    def __init__(
        self,
        save_root: str,
        *,
        finished_root: Optional[str] = None,
        nosync_root: Optional[str] = None,
    ) -> None:
        """Root the adapter at ``save_root`` (the active run root).

        ``save_root`` is the active root (in production it ends in a
        ``RUNS_ACTIVE`` segment). ``finished_root`` / ``nosync_root`` are the
        promotion targets used by :meth:`relocate_run`; when omitted they are
        derived from ``save_root`` by the legacy ``RUNS_ACTIVE`` ->
        ``RUNS_FINISHED`` / ``RUNS_NOSYNC`` string substitution (matching
        ``helao.helpers.yml_tools.move_dir``). If ``save_root`` carries no
        ``RUNS_ACTIVE`` segment and no explicit roots are given, the finished
        root collapses to ``save_root`` and :meth:`relocate_run` becomes a
        no-op (single-root adapters / tmp_path tests).
        """
        self.save_root = save_root
        if finished_root is None:
            finished_root = (
                save_root.replace("RUNS_ACTIVE", "RUNS_FINISHED")
                if "RUNS_ACTIVE" in save_root
                else save_root
            )
        if nosync_root is None:
            nosync_root = (
                save_root.replace("RUNS_ACTIVE", "RUNS_NOSYNC")
                if "RUNS_ACTIVE" in save_root
                else finished_root
            )
        self.finished_root = finished_root
        self.nosync_root = nosync_root

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

    # --- post-processor ---

    async def run_postprocessor(
        self, name: str, relpath: str, context: Mapping[str, Any]
    ) -> Sequence[Any]:
        # SP4 has no registered processors; the contract returns the file list
        # unchanged. Real processor dispatch is wired in app/ composition.
        return list(context.get("files", []))

    # --- whole-run-dir relocation at finish ---

    async def relocate_run(
        self, action_output_dir: str, sync_data: bool = True
    ) -> None:
        src_dir = os.path.normpath(os.path.join(self.save_root, action_output_dir))
        # finished destination for this action dir
        dst_dir = os.path.normpath(
            os.path.join(self.finished_root, action_output_dir)
        )
        if src_dir == dst_dir:
            # single-root adapter (no active/finished split) -> nothing to do.
            return
        if not os.path.isdir(src_dir):
            return

        # Mirror legacy move_dir(action): glob every file beneath the action
        # directory, copy each into the finished root (or no-sync root for .hlo
        # data when sync_data is False), then remove the active directory tree.
        src_list = [
            p
            for p in glob(os.path.join(src_dir, "**", "*"), recursive=True)
            if os.path.isfile(p)
        ]
        for src in src_list:
            rel = os.path.relpath(src, src_dir)
            if src.endswith(".hlo") and not sync_data:
                dst = os.path.join(self.nosync_root, action_output_dir, rel)
            else:
                dst = os.path.join(dst_dir, rel)
            await aiofiles.os.makedirs(os.path.dirname(dst), exist_ok=True)
            await aioshutil.copy(src, dst)

        # remove the now-promoted active directory tree
        await aioshutil.rmtree(src_dir)
