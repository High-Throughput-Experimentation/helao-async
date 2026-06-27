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

    def serialize_hlo_header(self, header: Mapping[str, Any]) -> str:
        """Serialize an HLO header ``dict`` to the YAML string written to disk.

        Mirrors legacy ``Base.init_datafile`` (``yml_dumps(hloheader.clean_dict())``,
        base.py:1298-1303): the domain builds a :class:`HloHeaderModel`, cleans it
        to a dict, and asks the storage layer to render it so YAML formatting stays
        an adapter concern (the domain stays free of serialization libraries).
        An empty mapping renders to ``""`` (no header block).
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

    async def relocate_dir(self, src_relpath: str, dst_relpath: str) -> str:
        """Move a whole run directory tree from ``src_relpath`` to ``dst_relpath``.

        Ports legacy ``move_dir`` (base.py:2218 / yml_tools.move_dir): a finished,
        non-manual action's output directory is promoted from the active location
        to the synced location so ``HelaoSyncer`` ships it. Both paths are relpaths
        beneath the storage root; the destination's parent is created on demand and
        the source subtree is moved (not copied). Returns ``dst_relpath``.
        """
        ...

    async def promote_run_dir(
        self,
        out_dir_relpath: str,
        *,
        manual: bool,
        sync_data: bool,
        recursive: bool,
    ) -> None:
        """Promote an object's run dir out of ``RUNS_ACTIVE`` (legacy ``move_dir``).

        File-granular port of ``helao.helpers.yml_tools.move_dir``. ``out_dir_relpath``
        is the object's output dir relative to the run-kind root (the same value
        stamped into ``*_output_dir``); the source is ``RUNS_ACTIVE/<out_dir_relpath>``.

        Destination base is ``RUNS_DIAG`` when ``manual`` else ``RUNS_FINISHED``.
        Each source file's destination keeps the same relpath with ``RUNS_ACTIVE``
        rewritten to ``RUNS_NOSYNC`` when the file ends with ``.hlo`` and
        ``sync_data`` is ``False``, otherwise to the destination base.

        ``recursive=True`` (actions) enumerates every file under the source tree;
        ``recursive=False`` (experiments/sequences) enumerates only the immediate
        files (children were already promoted by their own finishes). Non-NOSYNC
        files are copied, NOSYNC files are moved; then sources are removed and the
        emptied source dir is ``rmtree``'d. Missing/already-moved files are
        tolerated and any failure is logged and swallowed so finish never crashes.
        """
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
