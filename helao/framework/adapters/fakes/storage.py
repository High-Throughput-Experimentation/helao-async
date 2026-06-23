"""In-memory Storage backed by dicts, for tests.

Records JSON docs, streamed HLO buffers (header + ``%%\\n`` + rows), atomic
meta docs, relocations (src->dst), and post-processor invocations -- all in
memory so tests can assert without touching disk.
"""
import copy
from typing import Any, Mapping, Sequence

from helao.framework.ports.storage import Storage, StorageKeyError


class _FakeHloHandle:
    """Opaque handle for an open in-memory HLO buffer."""

    def __init__(self, relpath: str) -> None:
        self.relpath = relpath
        self.closed = False


class FakeStorage(Storage):
    """In-memory Storage recording every operation for assertions."""

    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}
        #: relpath -> accumulated HLO byte string (header + %%\n + rows).
        self.hlo_buffers: dict[str, str] = {}
        #: relpath -> meta doc written (deep-copied).
        self.meta_docs: dict[str, dict[str, Any]] = {}
        #: list of (src, dst) relocations recorded in order.
        self.relocations: list[tuple[str, str]] = []
        #: list of (name, relpath, context) post-processor calls.
        self.postproc_calls: list[tuple[str, str, dict[str, Any]]] = []
        #: list of (action_output_dir, sync_data) whole-run relocations.
        self.run_relocations: list[tuple[str, bool]] = []

    def write_json(self, relpath: str, payload: Mapping[str, Any]) -> str:
        self._docs[relpath] = copy.deepcopy(dict(payload))
        return relpath

    def read_json(self, relpath: str) -> Mapping[str, Any]:
        try:
            return copy.deepcopy(self._docs[relpath])
        except KeyError as exc:
            raise StorageKeyError(relpath) from exc

    async def open_hlo(self, relpath: str, header: str) -> _FakeHloHandle:
        buf = ""
        if header:
            if not header.endswith("\n"):
                header += "\n"
            buf += header
        buf += "%%\n"
        self.hlo_buffers[relpath] = buf
        return _FakeHloHandle(relpath)

    async def append_hlo(self, handle: _FakeHloHandle, row: str) -> None:
        if not row.endswith("\n"):
            row += "\n"
        self.hlo_buffers[handle.relpath] += row

    async def close_hlo(self, handle: _FakeHloHandle) -> None:
        handle.closed = True

    async def write_meta(self, relpath: str, doc: Mapping[str, Any]) -> str:
        self.meta_docs[relpath] = copy.deepcopy(dict(doc))
        return relpath

    async def relocate(self, src: str, dst: str) -> str:
        self.relocations.append((src, dst))
        return dst

    async def run_postprocessor(
        self, name: str, relpath: str, context: Mapping[str, Any]
    ) -> Sequence[Any]:
        self.postproc_calls.append((name, relpath, copy.deepcopy(dict(context))))
        return list(context.get("files", []))

    async def relocate_run(
        self, action_output_dir: str, sync_data: bool = True
    ) -> None:
        self.run_relocations.append((action_output_dir, sync_data))
