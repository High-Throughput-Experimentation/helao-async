"""ArtifactStorePort adapter (spec §4.3.3): wraps the legacy writers.

Meta ymls delegate to Base.write_act/write_exp/write_seq (atomic tmp +
os.replace, file_type first key, trailing newline — all inside legacy
base_meta_writer). Streamed/one-shot/finish members delegate to a BOUND
legacy Active (per-action handle via for_action). write_data_line feeds the
legacy data queue (Active.enqueue_data with a DataModel keyed by
file_conn_key) so the parity-critical lazy-open / %% / hlo_json_dumps chain
runs UNMODIFIED legacy code; close_streams maps to Active.substitute (the
"close every open HLO file" legacy seam); finish maps to Active.finish
(join-drain-close protocol §5.4). Promotion/zip delegate to
yml_tools.move_dir / file_utils.zip_dir.

Drift note (fixed here, not in legacy): ``yml_tools.move_dir`` has no
true success/failure return — it returns ``{}`` only when ``hobj`` is not a
supported Action/Experiment/Sequence type, and falls off the end (``None``)
on BOTH the successful-promotion path and the retries-exhausted-without-
raising path; that ambiguity is a pre-existing legacy limitation (success is
only observable via its LOGGER.info calls) and out of scope to fix without
editing legacy code. ``bool(result)`` would therefore always be ``False``
regardless of outcome. This adapter instead maps "legacy accepted a
recognized object type" (``result is not the {} rejection sentinel``) to the
port's ``-> bool`` contract, which is the most accurate signal the legacy
return value actually carries.
"""

from pathlib import Path
from typing import Optional, cast
from uuid import UUID

from helao.helpers.file_utils import zip_dir
from helao.helpers.yml_tools import move_dir
from helao.hexagon.adapters.errors import UnwiredPortError
from helao.hexagon.domain.models import Action, DataModel, Experiment, Sequence

__all__ = ["LegacyArtifactStoreAdapter"]


class LegacyArtifactStoreAdapter:
    def __init__(self, base, active=None):
        self._base = base
        self._active = active

    def for_action(self, active) -> "LegacyArtifactStoreAdapter":
        """Per-action handle bound to a live legacy Active."""
        return LegacyArtifactStoreAdapter(self._base, active=active)

    def _require_active(self):
        if self._active is None:
            raise UnwiredPortError(
                "stream/one-shot/finish members need an Active-bound handle; "
                "use for_action(active)"
            )
        return self._active

    # --- meta ymls ---
    async def write_act(self, action: Action) -> None:
        await self._base.write_act(action)

    async def write_exp(self, experiment: Experiment) -> None:
        await self._base.write_exp(experiment)

    async def write_seq(self, sequence: Sequence) -> None:
        await self._base.write_seq(sequence)

    # --- streamed hlo ---
    async def write_data_line(
        self, action: Action, file_conn_key: UUID, payload: object
    ) -> None:
        active = self._require_active()
        # the legacy streaming seam: DataModel keyed by file_conn_key; the
        # legacy log_data_task performs lazy open + header + %% + json line.
        # Port drift: write_data_line's `payload` is typed `object` (spec
        # §4.3.3), but legacy DataModel.data is Dict[UUID, dict] — every real
        # caller passes a dict row: the cast documents that parity
        # requirement rather than loosening DataModel itself.
        await active.enqueue_data(
            DataModel(data={file_conn_key: cast(dict, payload)}, errors=[]), action
        )

    async def close_streams(self, action: Action) -> None:
        await self._require_active().substitute()

    # --- one-shot ---
    async def write_one_shot(
        self,
        action: Action,
        output_str: str,
        file_type: str,
        filename: Optional[str],
        header: Optional[str],
    ) -> Optional[str]:
        return await self._require_active().write_file(
            output_str, file_type, filename, header=header, action=action
        )

    # --- finish + promotion ---
    async def finish(self, action: Action) -> None:
        await self._require_active().finish()

    async def move_dir(self, hobj: object) -> bool:
        result = await move_dir(hobj, base=self._base)
        # see module docstring "Drift note" — {} is legacy's only reject
        # signal; None covers both success and silent retry-exhaustion.
        return result != {}

    async def zip_dir(self, dir_path: Path) -> Path:
        target = Path(dir_path)
        out = target.with_suffix(".zip")
        zip_dir(target, out)
        return out
