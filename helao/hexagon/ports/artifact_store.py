"""ArtifactStore port (spec §4.3.3): meta ymls, HLO streams, promotion, zip.

Abstracts MetaFileWriter + DataFileWriter/DataStreamer file side + move_dir +
yml_finisher. ALL semantics below are parity-critical (spec §5):

- Atomic yml writes (temp file + os.replace), trailing newline,
  ``file_type:`` first key.
- LAZY hlo open on first data item per file_conn_key (mode ``w+``); header
  (HloHeaderModel.clean_dict()) at open; ``%%\\n`` before first data row; one
  JSON object per line; NaN/Infinity tokens legal; NO DATA => NO FILE; close
  at finish (or substitute).
- One-shot files: mode ``a+``, ``header + "%%\\n" + payload``, FileInfo
  appended at write; gated by ``save_data``.
- ``finish()`` JOINS the write queue before closing handles (drain protocol
  §5.4); late data beyond the bounded retries is dropped exactly as legacy
  drops it.
- ``move_dir`` promotion: RUNS_ACTIVE -> RUNS_FINISHED (manual -> RUNS_DIAG;
  ``.hlo`` with sync_data=False -> RUNS_NOSYNC); 60x/30x copy/remove retries;
  then DB-server ``/finish_yml`` handoff; fire-and-forget task semantics
  preserved.
"""

from pathlib import Path
from typing import Optional, Protocol, runtime_checkable
from uuid import UUID

from helao.hexagon.domain.models import Action, Experiment, Sequence

__all__ = ["ArtifactStorePort"]


@runtime_checkable
class ArtifactStorePort(Protocol):
    # --- meta ymls (atomic; file_type first key; same-name rewrite wins) ---
    async def write_act(self, action: Action) -> None: ...

    async def write_exp(self, experiment: Experiment) -> None: ...

    async def write_seq(self, sequence: Sequence) -> None: ...

    # --- streamed hlo (lazy open contract in module docstring) ---
    async def write_data_line(
        self, action: Action, file_conn_key: UUID, payload: object
    ) -> None:
        """Open-on-first-call for this key; header + %% precede the row."""
        ...

    async def close_streams(self, action: Action) -> None:
        """Close every open file handle for this action (finish step 3 /
        substitute)."""
        ...

    # --- one-shot files ---
    async def write_one_shot(
        self,
        action: Action,
        output_str: str,
        file_type: str,
        filename: Optional[str],
        header: Optional[str],
    ) -> Optional[str]: ...

    # --- finish + promotion ---
    async def finish(self, action: Action) -> None:
        """Join pending writes, close handles, final -act.yml rewrite."""
        ...

    async def move_dir(self, hobj: object) -> bool:
        """Promote a run dir per RunDir progression; returns success."""
        ...

    async def zip_dir(self, dir_path: Path) -> Path:
        """Zip a synced sequence dir (entries relative to seq dir, .prg
        included, .lock skipped, source dir deleted)."""
        ...
