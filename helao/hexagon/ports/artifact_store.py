"""ArtifactStore port (spec §4.3.3): meta ymls, HLO streams, promotion, zip.

Abstracts MetaFileWriter + DataFileWriter/DataStreamer file side + move_dir +
yml_finisher. ALL semantics below are parity-critical (spec §5). The streamed-hlo and
one-shot bullets are carried out by the native data writers; this port keeps
the meta, finish, promotion and zip members:

- Atomic yml writes (temp file + os.replace), trailing newline,
  ``file_type:`` first key.
- LAZY data open on first data item per file_conn_key (mode ``w+``); header
  (HloHeaderModel.clean_dict()) to ``X.meta.json`` at open; rows to
  ``X.jsonl``, one JSON object per line; NaN/Infinity tokens legal; NO DATA =>
  NO FILE; close at finish (or substitute).
- One-shot helao files: header overwritten, rows appended; aux files: mode
  ``a+``, ``header + "%%\\n" + payload``. FileInfo appended at write; gated
  by ``save_data``.
- ``finish()`` JOINS the write queue before closing handles (drain protocol
  §5.4); late data beyond the bounded retries is dropped exactly as legacy
  drops it.
- ``move_dir`` **finishes a record in place**: it appends the record's
  ``done`` eviction to the producing server's run-state journal and hands the
  yml to the syncer's ``/finish_yml``. **Nothing moves.** A record is written
  once, under ``<root>/RUNS`` (``<root>/DIAG`` for a manual run), and stays
  there; lifecycle state lives in the journal and the ``.prg`` receipt, not
  in a directory name. Withheld ``.hlo`` data stays in place too, excluded
  from upload by ``FileInfo.nosync`` rather than diverted to a parallel tree.
  Fire-and-forget task semantics preserved.

  This used to be a promotion -- ``RUNS_ACTIVE`` -> ``RUNS_FINISHED`` with
  60x/30x copy/remove retries -- and callers that still guard their call on
  the old meaning (e.g. skipping it for manual runs, or waiting for child
  directories to clear) now skip the eviction instead. See plan A34/A35.
- ``zip_dir`` is retained on the port but **no longer called on the sync
  path**: a synced sequence is not zipped (spec D9).
"""

from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from helao.hexagon.domain.models import Action, Experiment, Sequence

__all__ = ["ArtifactStorePort"]


@runtime_checkable
class ArtifactStorePort(Protocol):
    # --- meta ymls (atomic; file_type first key; same-name rewrite wins) ---
    async def write_act(self, action: Action, reason: Optional[str] = None) -> None: ...

    async def write_exp(self, experiment: Experiment) -> None: ...

    async def write_seq(self, sequence: Sequence) -> None: ...

    # --- finish + promotion ---
    async def finish(self, action: Action) -> None:
        """Join pending writes, close handles, final -act.yml rewrite."""
        ...

    async def move_dir(self, hobj: object) -> bool:
        """Finish a record in place: journal eviction + syncer handoff.

        Moves nothing. Returns success.
        """
        ...

    async def zip_dir(self, dir_path: Path) -> Path:
        """Zip a synced sequence dir (entries relative to seq dir, .prg
        included, .lock skipped, source dir deleted)."""
        ...
