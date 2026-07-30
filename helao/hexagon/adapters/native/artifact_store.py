"""ArtifactStorePort adapter over the NATIVE write bodies (P2b-1).

The native counterpart of ``adapters/legacy/artifact_store.py``: the same
port surface and the same for_action/bound-handle pattern, but every write
body is the hexagon-native re-body (meta_writer/data_file/data_stream/
finalizer modules in this package) instead of a wrap of live legacy
collaborators. Constructible from ConfigPort+ClockPort at ``build_wiring``
time — no live ``Base`` exists yet; ``bind_base`` is called by the active
graft at startup (the late-binding pattern the status adapter documents for
its queues). It is also the composition's collaborator FACTORY:
``graft_active_write_path`` obtains the per-Active native collaborators via
``collaborators_for`` and the per-Base meta writer via ``meta_writer_for``,
so the fail-loud wired port is exactly what carries the rerouted traffic
(honesty: an unwired artifact_store aborts startup via ACTION_REQUIRED).

Promotion/zip stay keep-callable legacy helpers (``yml_tools.move_dir`` /
``file_utils.zip_dir``) — helpers, not god-class members. The ``move_dir``
``{}``-rejection-sentinel mapping is copied from the legacy adapter's
documented drift note: ``{}`` is legacy's only reject signal; ``None``
covers both success and silent retry-exhaustion, so "recognized object
type" (``result != {}``) is the most accurate bool the return carries.

Q2 (binding): sample/status mutations are NOT here — see
``native/data_sink.py``.
"""

from pathlib import Path
from typing import Optional
from uuid import UUID

from helao.helpers.file_utils import zip_dir
from helao.helpers.yml_tools import move_dir
from helao.hexagon.adapters.errors import UnwiredPortError
from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
from helao.hexagon.adapters.native.data_stream import NativeDataStreamer
from helao.hexagon.adapters.native.finalizer import NativeActionFinalizer
from helao.hexagon.adapters.native.meta_writer import NativeMetaFileWriter
from helao.hexagon.domain.models import Action, DataModel, Experiment, Sequence

__all__ = ["NativeArtifactStoreAdapter"]


class NativeArtifactStoreAdapter:
    def __init__(self, config=None, clock=None, base=None, active=None):
        self._config = config
        self._clock = clock
        self._base = base
        self._active = active

    # --- graft-time binding + collaborator factory ---
    def bind_base(self, base) -> None:
        """Late base binding (graft startup); build_wiring has no Base yet."""
        self._base = base

    def meta_writer_for(self, base) -> NativeMetaFileWriter:
        return NativeMetaFileWriter(base)

    def collaborators_for(
        self, active
    ) -> tuple[NativeDataStreamer, NativeDataFileWriter, NativeActionFinalizer]:
        """Per-Active native collaborator set (cache-nothing: each holds only
        the back-reference; safe to construct fresh per Active)."""
        return (
            NativeDataStreamer(active),
            NativeDataFileWriter(active),
            NativeActionFinalizer(active),
        )

    def for_action(self, active) -> "NativeArtifactStoreAdapter":
        """Per-action handle bound to a live (grafted) legacy Active."""
        return NativeArtifactStoreAdapter(
            config=self._config, clock=self._clock, base=self._base, active=active
        )

    def _require_base(self):
        if self._base is None:
            raise UnwiredPortError(
                "meta members need a bound Base; the active graft calls "
                "bind_base(base) at startup"
            )
        return self._base

    def _require_active(self):
        if self._active is None:
            raise UnwiredPortError(
                "stream/one-shot/finish members need an Active-bound handle; "
                "use for_action(active)"
            )
        return self._active

    # --- meta ymls (native bodies, resolved through the bound base's
    # meta_writer — the graft has already swapped it native) ---
    async def write_act(self, action: Action) -> None:
        await self._require_base().write_act(action)

    async def write_exp(self, experiment: Experiment) -> None:
        await self._require_base().write_exp(experiment)

    async def write_seq(self, sequence: Sequence) -> None:
        await self._require_base().write_seq(sequence)

    # --- streamed hlo ---
    async def write_data_line(
        self, action: Action, file_conn_key: UUID, payload: object
    ) -> None:
        active = self._require_active()
        # native enqueue re-body via the swapped collaborator: DataModel keyed
        # by file_conn_key; the native log_data_task performs lazy open +
        # header + %% + json line. payload is dict-per-row in every real
        # caller (same cast rationale as the legacy adapter).
        await NativeDataStreamer(active).enqueue_data(
            DataModel(data={file_conn_key: payload}, errors=[]), action  # type: ignore[dict-item]
        )

    async def close_streams(self, action: Action) -> None:
        await NativeActionFinalizer(self._require_active()).substitute()

    # --- one-shot ---
    async def write_one_shot(
        self,
        action: Action,
        output_str: str,
        file_type: str,
        filename: Optional[str],
        header: Optional[str],
    ) -> Optional[str]:
        return await NativeDataFileWriter(self._require_active()).write_file(
            output_str, file_type, filename, header=header, action=action
        )

    # --- finish + promotion ---
    async def finish(self, action: Action) -> None:
        await NativeActionFinalizer(self._require_active()).finish()

    async def move_dir(self, hobj: object) -> bool:
        result = await move_dir(hobj, base=self._base)
        # {} is legacy's only reject signal (see module docstring)
        return result != {}

    async def zip_dir(self, dir_path: Path) -> Path:
        target = Path(dir_path)
        out = target.with_suffix(".zip")
        zip_dir(target, out)
        return out
