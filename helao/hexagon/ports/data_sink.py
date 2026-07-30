"""DataSink port (spec §4.3.2): what executors/drivers actually need from Active.

Precedent: cNIMAX.arm_cell_iv receiving plain callables (enqueue_data_nowait,
get_realtime_nowait, finish_hlo_header) — the best-in-tree pattern. Replaces
the ``active.base.app.driver...`` object-graph handouts and the PAL per-job
injected Active.

THREAD-SAFETY IS CONTRACTUAL: members suffixed ``_nowait`` plus
``realtime_ns`` MUST be callable from a foreign thread (the NI-DAQmx hardware
buffer callback). All other members are event-loop-affine.

Signatures mirror the legacy Active surface verbatim
(helao/core/servers/base.py:1155-1380, active_data_stream.py,
active_finalizer.py) so P1b adapters are thin delegation.
"""

from typing import Optional, Protocol, Union, runtime_checkable
from uuid import UUID

from helao.hexagon.domain.models import (
    Action,
    AssemblySample,
    DataModel,
    FileConnParams,
    GasSample,
    HloFileGroup,
    LiquidSample,
    NoneSample,
    SolidSample,
)

__all__ = ["DataSinkPort"]

_Sample = Union[AssemblySample, LiquidSample, GasSample, SolidSample, NoneSample]


@runtime_checkable
class DataSinkPort(Protocol):
    # --- data stream (thread-safe where noted) ---
    async def enqueue_data(
        self, datamodel: DataModel, action: Optional[Action] = None
    ) -> None: ...

    def enqueue_data_nowait(
        self, datamodel: DataModel, action: Optional[Action] = None
    ) -> None:
        """THREAD-SAFE."""
        ...

    async def enqueue_data_dflt(self, datadict: dict) -> None: ...

    def get_realtime_nowait(
        self, epoch_ns: Optional[int] = None, offset: Optional[float] = None
    ) -> int:
        """THREAD-SAFE. NTP-corrected epoch nanoseconds."""
        ...

    async def finish_hlo_header(
        self,
        file_conn_keys: Optional[list[UUID]] = None,
        realtime: Optional[int] = None,
    ) -> None: ...

    # --- file output ---
    async def write_file(
        self,
        output_str: str,
        file_type: str,
        filename: Optional[str] = None,
        file_group: HloFileGroup = HloFileGroup.aux_files,
        header: Optional[str] = None,
        sample_str: Optional[str] = None,
        file_sample_label: Optional[Union[list[str], str]] = None,
        json_data_keys: Optional[list[str]] = None,
        action: Optional[Action] = None,
    ) -> Optional[str]: ...

    def write_file_nowait(
        self,
        output_str: str,
        file_type: str,
        filename: Optional[str] = None,
        file_group: HloFileGroup = HloFileGroup.aux_files,
        header: Optional[str] = None,
        sample_str: Optional[str] = None,
        file_sample_label: Optional[Union[list[str], str]] = None,
        json_data_keys: Optional[list[str]] = None,
        action: Optional[Action] = None,
    ) -> Optional[str]:
        """THREAD-SAFE."""
        ...

    async def track_file(
        self,
        file_type: str,
        file_path: str,
        samples: list[_Sample],
        action: Optional[Action] = None,
    ) -> None: ...

    # --- sample bookkeeping ---
    async def append_sample(
        self, samples: list[_Sample], IO: str, action: Optional[Action] = None
    ) -> None: ...

    # --- lifecycle ---
    async def split(
        self,
        uuid_list: Optional[list[UUID]] = None,
        new_fileconnparams: Optional[FileConnParams] = None,
    ) -> list[UUID]: ...

    def set_estop(self, action: Optional[Action] = None) -> None:
        """THREAD-SAFE."""
        ...

    # --- live buffer ---
    async def put_lbuf(self, payload: dict) -> None: ...

    def put_lbuf_nowait(self, payload: dict) -> None:
        """THREAD-SAFE."""
        ...

    def get_lbuf(self, key: str) -> tuple: ...
