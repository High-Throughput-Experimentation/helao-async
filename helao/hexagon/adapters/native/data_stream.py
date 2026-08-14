"""Native data streamer (hexagon P2b-1).

Verbatim re-body of the CARDS-P6 ``DataStreamer`` collaborator
(``helao/core/servers/active_data_stream.py``): realtime-clock forwarders,
live-data appender, the ``enqueue_data*`` -> ``data_q`` publish path (queued
counter bumped only for data-bearing packets), and the ``log_data_task``
drain loop -- subscribe, listen-uuid filter, LAZY file open on the first
matching packet (json_data_keys inferred from the first row when unset),
``%%`` separator exactly once via ``added_hlo_separator``, ``hlo_json_dumps``
rows, non-serializable payload -> ``{"error": "data was not serializable"}``,
string payloads written raw, ``num_data_written`` bump per data-bearing
packet, subscription removal on cancel. Method bodies are byte-identical to
legacy (source-parity-pinned by ``test_native_data_stream.py``); only this
docstring, the class name, and ``__all__`` differ.

Per-Active collaborator: holds only the ``active`` back-reference; all
counters/uuid lists/queues stay on ``Active``/``Base`` and are resolved at
call time (cache-nothing rule -- the ce846da1 failure class). Swapped in for
``active.data_stream`` by ``graft_active_write_path`` between
``Active.__init__`` and ``myinit()`` -- BEFORE ``myinit`` creates the
``data_logger`` task (``base.py:1014``), so the drain loop only ever runs
native code. Cross-collaborator hops stay routed through the ``Active``
surface (``self.active.write_live_data`` / ``self.active.log_data_set_output_file``),
exactly as legacy.
"""

# The Optional-narrowing diagnostics below (assemble_data_msg's `action`
# parameter defaults through `self.active.action`, a nominally-Optional
# attribute, before its `action_uuid`/`action_name` are read) are
# pre-existing in the legacy body this module re-bodies verbatim (confirmed:
# `pyright helao/core/servers/active_data_stream.py` reports the same
# rule-types on the unmodified legacy file). Source-parity pins the method
# bodies byte-identical to legacy, so they cannot be touched here; suppressed
# at file scope instead of inline to avoid perturbing `inspect.getsource`.
# pyright: reportArgumentType=false, reportOptionalMemberAccess=false

import asyncio
import traceback
from typing import Optional
from uuid import UUID

import numpy as np

from helao.core.models.data import DataModel, DataPackageModel
from helao.core.models.hlostatus import HloStatus
from helao.helpers import helao_logging as logging
from helao.helpers.premodels import Action
from helao.helpers.to_json import hlo_json_dumps
from helao.hexagon.ports.action_session import ActionSessionPort

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = ["NativeDataStreamer"]


class NativeDataStreamer:
    """Native drop-in for ``active.data_stream`` (legacy surface, native body).

    Holds only the ``active`` back-reference (never cached queue/counter/uuid
    state), per the call-time state resolution rule -- see module docstring.

    The back-reference is declared at class level rather than annotated on the
    ``__init__`` parameter: ``__init__`` is byte-pinned against its legacy twin
    by ``assert_source_parity`` (see ``native_fixtures``), and an annotation in
    the signature would change ``inspect.getsource(__init__)`` and break the
    pin. A class-level annotation gives static checking without touching the
    pinned method source.
    """

    active: ActionSessionPort

    def __init__(self, active):
        self.active = active

    async def get_realtime(
        self, epoch_ns: Optional[int] = None, offset: Optional[float] = None
    ) -> int:
        """Forward to :meth:`Base.get_realtime` for NTP-corrected nanoseconds."""
        return await self.active.base.get_realtime(epoch_ns=epoch_ns, offset=offset)

    def get_realtime_nowait(
        self, epoch_ns: Optional[int] = None, offset: Optional[float] = None
    ) -> int:
        """Return NTP-corrected nanoseconds from the base controller (non-async)."""
        return int(
            np.floor(self.active.base.get_realtime_nowait(epoch_ns=epoch_ns, offset=offset))
        )

    async def write_live_data(self, output_str: str, file_conn_key: UUID):
        """Append ``output_str`` (with a trailing newline) to the open file for ``file_conn_key``.

        Returns:
            None
        """
        if file_conn_key in self.active.file_conn_dict:
            if self.active.file_conn_dict[file_conn_key].file:
                if not output_str.endswith("\n"):
                    output_str += "\n"
                await self.active.file_conn_dict[file_conn_key].file.write(output_str)

    async def enqueue_data_dflt(self, datadict: dict):
        """Enqueue ``datadict`` against the default file-connection key as an active ``DataModel``."""
        await self.active.enqueue_data(
            datamodel=DataModel(
                data={self.active.base.dflt_file_conn_key(): datadict},
                errors=[],
                status=HloStatus.active,
            )
        )

    def _build_data_package(
        self, datamodel: DataModel, action: Optional[Action] = None
    ) -> tuple:
        """Return ``(DataPackageModel, has_data)`` derived from ``datamodel`` and ``action``."""
        if action is None:
            action = self.active.action
        return self.active.assemble_data_msg(datamodel=datamodel, action=action), bool(datamodel.data)

    async def enqueue_data(self, datamodel: DataModel, action: Optional[Action] = None):
        """Publish ``datamodel`` onto the data queue and bump the queued counter if it had data."""
        msg, has_data = self.active._build_data_package(datamodel, action)
        await self.active.base.data_q.put(msg)
        if has_data:
            self.active.num_data_queued += 1

    def enqueue_data_nowait(
        self, datamodel: DataModel, action: Optional[Action] = None
    ):
        """Non-awaiting variant of :meth:`enqueue_data`."""
        msg, has_data = self.active._build_data_package(datamodel, action)
        self.active.base.data_q.put_nowait(msg)
        if has_data:
            self.active.num_data_queued += 1

    def assemble_data_msg(
        self, datamodel: DataModel, action: Optional[Action] = None
    ) -> DataPackageModel:
        """Wrap a ``DataModel`` and ``Action`` into a ``DataPackageModel`` for the data queue."""
        if action is None:
            action = self.active.action
        return DataPackageModel(
            action_uuid=action.action_uuid,
            action_name=action.action_name,
            datamodel=datamodel,
            errors=datamodel.errors,
        )

    def add_new_listen_uuid(self, new_uuid: UUID):
        """Track ``new_uuid`` as a data-stream source for this active's data logger."""
        self.active.listen_uuids.append(new_uuid)

    async def log_data_task(self):
        """Subscribe to the data queue and write matching packets to the active's HLO files.

        Filters by tracked listen UUIDs, lazily opens output files, writes the
        HLO ``%%`` separator before the first data row, and serialises dict
        payloads as JSON. Runs until cancelled when the action finishes.
        """
        if not self.active.action.save_data:
            LOGGER.info("data writing disabled")
            return

        # self.active.base.print_message(
        #     f"starting data LOGGER for active action: {self.active.action.action_uuid}",
        #     info=True,
        # )

        dq_sub = self.active.base.data_q.subscribe()

        try:
            async for data_msg in dq_sub:
                # check if the new data_msg is in listen_uuids
                if data_msg.action_uuid not in self.active.listen_uuids:
                    continue

                data_status = data_msg.datamodel.status
                data_dict = data_msg.datamodel.data

                self.active.action.data_stream_status = data_status

                if data_status not in (None, HloStatus.active):
                    LOGGER.debug(
                        f"data_stream: skipping package for status: {data_status}"
                    )
                    continue

                for file_conn_key, sample_data in data_dict.items():
                    output_action = self.active._get_action_for_file_conn_key(
                        file_conn_key=file_conn_key
                    )
                    if output_action is None:
                        LOGGER.error(
                            "data LOGGER could not find action for file_conn_key"
                        )
                        continue

                    if file_conn_key not in self.active.file_conn_dict:
                        if output_action.save_data:
                            LOGGER.warning(
                                f"'{file_conn_key}' does not exist in file_conn '{self.active.file_conn_dict}'."
                            )
                        else:
                            # got data but saving is disabled,
                            # e.g. no file was created,
                            # e.g. file_conn_key is not in self.active.file_conn_dict
                            LOGGER.info(
                                "data logging is disabled for action '{output_action.action_name}'"
                            )

                        continue

                    # check if we need to create the file first
                    if self.active.file_conn_dict[file_conn_key].file is None:
                        if not self.active.file_conn_dict[file_conn_key].params.json_data_keys:
                            jsonkeys = [key for key in sample_data.keys()]
                            LOGGER.debug(
                                "no json_data_keys defined, using keys from first data message: {jsonkeys[:10]}"
                            )

                            self.active.file_conn_dict[file_conn_key].params.json_data_keys = (
                                jsonkeys
                            )

                        LOGGER.debug(f"creating output file for {file_conn_key}")
                        # create the file for this data stream
                        await self.active.log_data_set_output_file(file_conn_key=file_conn_key)

                    # write only data if the file connection is open
                    if self.active.file_conn_dict[file_conn_key].file:
                        # check if separator was already written
                        # else add it
                        if not self.active.file_conn_dict[file_conn_key].added_hlo_separator:
                            self.active.file_conn_dict[file_conn_key].added_hlo_separator = (
                                True
                            )
                            await self.active.write_live_data(
                                output_str="%%\n",
                                file_conn_key=file_conn_key,
                            )

                        if isinstance(sample_data, dict):
                            try:
                                output_str = hlo_json_dumps(sample_data)
                            except TypeError:
                                LOGGER.error("Data is not json serializable.")
                                output_str = hlo_json_dumps(
                                    {"error": "data was not serializable"}
                                )
                            await self.active.write_live_data(
                                output_str=output_str,
                                file_conn_key=file_conn_key,
                            )
                        else:
                            await self.active.write_live_data(
                                output_str=sample_data, file_conn_key=file_conn_key
                            )
                    else:
                        LOGGER.error("output file closed?")
                if data_dict:
                    self.active.num_data_written += 1

        except asyncio.CancelledError:
            LOGGER.debug("removing data_q subscription for active")
            if dq_sub in self.active.base.data_q.subscribers:
                self.active.base.data_q.remove(dq_sub)
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            LOGGER.error(f"data LOGGER task failed with error: {repr(e), tb,}")
