"""DataSinkPort adapter over the NATIVE write bodies (P2b-1).

Write members (enqueue*/realtime/finish_hlo_header/write_file*/track_file/
split) run the native collaborator bodies in this package, constructed
per-call against the bound Active (cache-nothing: collaborators hold only
the back-ref; every counter/conn lives on the Active, so fresh construction
is state-free). THREAD-SAFETY IS CONTRACTUAL and preserved verbatim: the
``_nowait`` members and ``get_realtime_nowait`` execute the byte-identical
legacy bodies (source-parity-pinned), which are the members the NI-DAQmx
hardware-buffer callback calls from a foreign thread.

Q2 (binding): ``append_sample`` and ``set_estop`` STAY legacy-delegated onto
the Active surface (pure mutations on shared pydantic models + a status_q
put; P2a owns the status plane — reimplementing them buys no decoupling
while legacy BaseAPI hosts). The lbuf members route via ``active.base`` —
the ONE sanctioned base reach-in, same as the legacy adapter.
"""

from typing import List, Optional
from uuid import UUID

from helao.hexagon.adapters.errors import UnwiredPortError
from helao.hexagon.adapters.native.data_file import NativeDataFileWriter
from helao.hexagon.adapters.native.data_stream import NativeDataStreamer
from helao.hexagon.adapters.native.finalizer import NativeActionFinalizer
from helao.hexagon.domain.models import (
    Action,
    DataModel,
    FileConnParams,
    HloFileGroup,
)

__all__ = ["NativeDataSinkAdapter"]


class NativeDataSinkAdapter:
    def __init__(self, active=None):
        self._active = active

    def for_action(self, active) -> "NativeDataSinkAdapter":
        """Per-action handle bound to a live (grafted) legacy Active."""
        return NativeDataSinkAdapter(active=active)

    def _require_active(self):
        if self._active is None:
            raise UnwiredPortError(
                "data-sink members need an Active-bound handle; use "
                "for_action(active)"
            )
        return self._active

    def _streamer(self) -> NativeDataStreamer:
        return NativeDataStreamer(self._require_active())

    def _file_writer(self) -> NativeDataFileWriter:
        return NativeDataFileWriter(self._require_active())

    # --- data stream (thread-safe where noted; native bodies) ---
    async def enqueue_data(
        self, datamodel: DataModel, action: Optional[Action] = None
    ) -> None:
        await self._streamer().enqueue_data(datamodel, action)

    def enqueue_data_nowait(
        self, datamodel: DataModel, action: Optional[Action] = None
    ) -> None:
        self._streamer().enqueue_data_nowait(datamodel, action)

    async def enqueue_data_dflt(self, datadict: dict) -> None:
        await self._streamer().enqueue_data_dflt(datadict)

    def get_realtime_nowait(
        self, epoch_ns: Optional[int] = None, offset: Optional[float] = None
    ) -> int:
        return self._streamer().get_realtime_nowait(epoch_ns=epoch_ns, offset=offset)

    async def finish_hlo_header(
        self,
        file_conn_keys: Optional[List[UUID]] = None,
        realtime: Optional[int] = None,
    ) -> None:
        # legacy finish_hlo_header is sync (base.py:1091); async-first port,
        # plain call inside the coroutine keeps semantics (legacy-adapter
        # precedent).
        self._file_writer().finish_hlo_header(
            file_conn_keys=file_conn_keys, realtime=realtime
        )

    # --- file output (native bodies) ---
    async def write_file(
        self,
        output_str,
        file_type,
        filename=None,
        file_group=HloFileGroup.aux_files,
        header=None,
        sample_str=None,
        file_sample_label=None,
        json_data_keys=None,
        action=None,
    ):
        return await self._file_writer().write_file(
            output_str,
            file_type,
            filename=filename,
            file_group=file_group,
            header=header,
            sample_str=sample_str,
            file_sample_label=file_sample_label,
            json_data_keys=json_data_keys,
            action=action,
        )

    def write_file_nowait(
        self,
        output_str,
        file_type,
        filename=None,
        file_group=HloFileGroup.aux_files,
        header=None,
        sample_str=None,
        file_sample_label=None,
        json_data_keys=None,
        action=None,
    ):
        return self._file_writer().write_file_nowait(
            output_str,
            file_type,
            filename=filename,
            file_group=file_group,
            header=header,
            sample_str=sample_str,
            file_sample_label=file_sample_label,
            json_data_keys=json_data_keys,
            action=action,
        )

    async def track_file(self, file_type, file_path, samples, action=None) -> None:
        await self._file_writer().track_file(
            file_type, file_path, samples, action=action
        )

    # --- sample bookkeeping / estop: LEGACY-delegated (Q2, binding) ---
    async def append_sample(self, samples, IO, action=None) -> None:
        await self._require_active().append_sample(samples, IO=IO, action=action)

    def set_estop(self, action: Optional[Action] = None) -> None:
        self._require_active().set_estop(action)

    # --- lifecycle (finalizer trio is native scope) ---
    async def split(
        self, uuid_list=None, new_fileconnparams: Optional[FileConnParams] = None
    ):
        return await NativeActionFinalizer(self._require_active()).split(
            uuid_list=uuid_list, new_fileconnparams=new_fileconnparams
        )

    # --- live buffer (via active.base — the sanctioned reach-in) ---
    async def put_lbuf(self, payload: dict) -> None:
        await self._require_active().base.put_lbuf(payload)

    def put_lbuf_nowait(self, payload: dict) -> None:
        self._require_active().base.put_lbuf_nowait(payload)

    def get_lbuf(self, key: str) -> tuple:
        return self._require_active().base.get_lbuf(key)
