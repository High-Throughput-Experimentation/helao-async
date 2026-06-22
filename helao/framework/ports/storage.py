"""Storage port: persist JSON docs and stream/finalize HLO + meta files.

Pure port (Protocols + typing only -- no I/O libraries). The action path
needs, beyond plain JSON docs:

- streaming HLO output: open a file connection (which writes the YAML header
  followed by the ``%%`` separator), append data rows, and close it;
- atomic meta-file writes (``.act``/``.exp``/``.seq`` YAML) via temp-file +
  replace, so readers never observe a torn file;
- relocating (copying) an auxiliary file into the run directory;
- running a registered HLO post-processor over a finished file.

The legacy byte layout this mirrors (``helao.core.servers.base``) is::

    [HEADER]\\n%%\\n[JSON ROW]\\n[JSON ROW]\\n...

The fake records everything in memory; the real adapter lives in
``adapters/fs_storage.py``.
"""
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


class StorageKeyError(KeyError):
    """Raised when reading a relpath that was never written."""


@runtime_checkable
class Storage(Protocol):
    """Persists JSON documents, streaming HLO files, and atomic meta files."""

    def write_json(self, relpath: str, payload: Mapping[str, Any]) -> str:
        """Write payload as JSON at relpath; return the relpath written."""
        ...

    def read_json(self, relpath: str) -> Mapping[str, Any]:
        """Read and return the JSON document at relpath.

        Raises StorageKeyError if relpath was never written.
        """
        ...

    async def open_hlo(self, relpath: str, header: str) -> Any:
        """Open an HLO file connection at ``relpath`` and return an opaque handle.

        Writes ``header`` (a trailing newline is ensured) followed by the HLO
        ``%%`` separator row, so the file is positioned ready for data rows.
        ``header`` may be empty/``""`` to skip the header block.
        """
        ...

    async def append_hlo(self, handle: Any, row: str) -> None:
        """Append a single data ``row`` to an open HLO ``handle``.

        A trailing newline is ensured so each row occupies its own line.
        """
        ...

    async def close_hlo(self, handle: Any) -> None:
        """Close a previously opened HLO ``handle``."""
        ...

    async def write_meta(self, relpath: str, doc: Mapping[str, Any]) -> str:
        """Atomically write ``doc`` as YAML meta at ``relpath``; return relpath.

        Used for ``.act``/``.exp``/``.seq`` (or ``-act.yml`` etc.) meta files.
        Implementations write to a temp file in the same directory and replace
        the target in one step so readers never see a partial file.
        """
        ...

    async def relocate(self, src: str, dst: str) -> str:
        """Copy ``src`` to ``dst`` (relocating an aux file); return ``dst``."""
        ...

    async def run_postprocessor(
        self, name: str, relpath: str, context: Mapping[str, Any]
    ) -> Sequence[Any]:
        """Run the named HLO post-processor over ``relpath``.

        Returns the (possibly updated) file list the processor produced.
        ``context`` carries whatever the processor needs (e.g. action info,
        save root). Pure ports define the contract only.
        """
        ...
