"""DataSinkPort adapter (spec §4.3.2): verbatim delegation onto a legacy
Active. Thread-safety contract rides on the wrapped members themselves
(the *_nowait members and get_realtime_nowait are the legacy thread-safe
surface the NI-DAQmx callback already uses). The lbuf members route via
active.base — the ONE sanctioned base reach-in; this port exists precisely
to replace the 72 scattered active.action / 18 full-Base reach-ins."""

from typing import Optional
from uuid import UUID

from helao.hexagon.domain.models import (
    Action,
    DataModel,
    FileConnParams,
    HloFileGroup,
)

__all__ = ["ActiveDataSinkAdapter"]


class ActiveDataSinkAdapter:
    def __init__(self, active):
        self._active = active

    # --- data stream ---
    async def enqueue_data(
        self, datamodel: DataModel, action: Optional[Action] = None
    ) -> None:
        await self._active.enqueue_data(datamodel, action)

    def enqueue_data_nowait(
        self, datamodel: DataModel, action: Optional[Action] = None
    ) -> None:
        self._active.enqueue_data_nowait(datamodel, action)

    async def enqueue_data_dflt(self, datadict: dict) -> None:
        await self._active.enqueue_data_dflt(datadict)

    def get_realtime_nowait(
        self, epoch_ns: Optional[int] = None, offset: Optional[float] = None
    ) -> int:
        return self._active.get_realtime_nowait(epoch_ns, offset)

    async def finish_hlo_header(
        self,
        file_conn_keys: Optional[list[UUID]] = None,
        realtime: Optional[int] = None,
    ) -> None:
        # legacy Active.finish_hlo_header is sync (base.py:1091); the port is
        # async-first — plain call inside the coroutine keeps semantics.
        self._active.finish_hlo_header(file_conn_keys, realtime)

    # --- file output ---
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
        return await self._active.write_file(
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
        return self._active.write_file_nowait(
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
        await self._active.track_file(file_type, file_path, samples, action=action)

    # --- sample bookkeeping / lifecycle ---
    async def append_sample(self, samples, IO, action=None) -> None:
        await self._active.append_sample(samples, IO=IO, action=action)

    async def split(
        self, uuid_list=None, new_fileconnparams: Optional[FileConnParams] = None
    ):
        return await self._active.split(
            uuid_list=uuid_list, new_fileconnparams=new_fileconnparams
        )

    def set_estop(self, action: Optional[Action] = None) -> None:
        self._active.set_estop(action)

    # --- live buffer (via active.base — the sanctioned reach-in) ---
    async def put_lbuf(self, payload: dict) -> None:
        await self._active.base.put_lbuf(payload)

    def put_lbuf_nowait(self, payload: dict) -> None:
        self._active.base.put_lbuf_nowait(payload)

    def get_lbuf(self, key: str) -> tuple:
        return self._active.base.get_lbuf(key)
