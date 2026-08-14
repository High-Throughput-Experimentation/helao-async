"""The interface the native write collaborators require of an action session.

**This Protocol is derived, not authored.** Its 26 members are exactly what
``adapters/native/{data_stream,data_file,finalizer}.py`` read off their
``self.active`` back-reference, extracted by AST walk on 2026-08-14 and split
into 9 async methods, 7 sync methods and 10 attributes. Needing to add a member
by hand later — because something failed at runtime — means the derivation was
incomplete: re-run it across all three modules rather than patching the member
in.

Why it exists (spec D-B1.3, superseded and re-decided). B1 set out to give the
native session the 18-member surface deployment code actually uses. That is the
deployment-facing contract and it is correct as far as it goes, but it is not
the whole one: the three collaborators were written against the legacy
``Active`` and reach for 26 members, **19 of which are not in the 18**. A
session built to 18 would import, register, serve, and then fail at the first
``enqueue_data`` with a bare ``AttributeError`` raised from inside a
collaborator, at the moment an action is writing data to disk.

Rather than have the session silently owe an interface nobody wrote down, the
collaborators depend on this Protocol. Their bodies are unchanged; only their
declared dependency moves. That makes the coupling explicit and checkable, and
means a future session implementation is told what it owes at type-check time
instead of at 3am on a station.

The signatures are `Active`'s own, so a legacy `Active` satisfies this Protocol
structurally and the collaborators keep working against either.
"""

from typing import Optional, Protocol, runtime_checkable
from uuid import UUID

from helao.core.models.data import DataModel, DataPackageModel
from helao.core.models.file import FileConnParams, HloFileGroup
from helao.helpers.premodels import Action

__all__ = ["ActionSessionPort"]


@runtime_checkable
class ActionSessionPort(Protocol):
    """What ``data_stream``, ``data_file`` and ``finalizer`` need from a session.

    ``runtime_checkable`` so a composition can assert the binding at wire-up
    time. Note that a runtime ``isinstance`` check against a Protocol verifies
    only that the *names* exist, not their signatures — it catches a session
    missing a member, not one whose method takes the wrong arguments. Static
    checking is what covers the second case, which is the main reason this file
    carries real signatures rather than ``*args``.
    """

    # -- attributes ----------------------------------------------------------

    #: The action this session is tracking.
    action: Action
    #: Every action in the session, including those produced by a split.
    action_list: list
    #: This session's own uuid.
    active_uuid: UUID
    #: The hosting action server.
    base: object
    #: The running data-logging task, or None.
    data_logger: object
    #: Open file connections keyed by file_conn_key.
    file_conn_dict: dict
    #: Serializes concurrent finish attempts.
    finish_lock: object
    #: Action uuids whose data this session is listening for.
    listen_uuids: list
    #: Count of data messages enqueued.
    num_data_queued: int
    #: Count of data messages written.
    num_data_written: int

    # -- async methods -------------------------------------------------------

    async def _finish(
        self, finish_uuid_list: Optional[list[UUID]] = None
    ) -> Action: ...

    async def add_status(self, action: Optional[Action] = None) -> None: ...

    async def enqueue_data(
        self, datamodel: DataModel, action: Optional[Action] = None
    ) -> None: ...

    async def finish(self, finish_uuid_list: Optional[list[UUID]] = None) -> Action: ...

    async def finish_manual_action(self) -> None: ...

    async def get_realtime(
        self, epoch_ns: Optional[int] = None, offset: Optional[float] = None
    ) -> int: ...

    async def log_data_set_output_file(self, file_conn_key: UUID) -> None: ...

    async def split(
        self,
        uuid_list: Optional[list[UUID]] = None,
        new_fileconnparams: Optional[FileConnParams] = None,
    ) -> list[UUID]: ...

    async def write_live_data(self, output_str: str, file_conn_key: UUID) -> None: ...

    # -- sync methods --------------------------------------------------------

    def _build_data_package(
        self, datamodel: DataModel, action: Optional[Action] = None
    ) -> tuple: ...

    def _get_action_for_file_conn_key(
        self, file_conn_key: UUID
    ) -> Optional[Action]: ...

    def _resolve_output_path(
        self,
        file_type: str,
        filename: Optional[str],
        file_group: HloFileGroup,
        header: Optional[str],
        file_sample_label,
        json_data_keys,
        action: Action,
    ) -> None: ...

    def add_new_listen_uuid(self, new_uuid: UUID) -> None: ...

    def assemble_data_msg(
        self, datamodel: DataModel, action: Optional[Action] = None
    ) -> DataPackageModel: ...

    def get_realtime_nowait(self) -> int: ...

    def init_datafile(
        self,
        header,
        file_type,
        json_data_keys,
        file_sample_label,
        filename,
        file_group: HloFileGroup,
        file_conn_key: Optional[str] = None,
        action: Optional[Action] = None,
    ) -> tuple: ...
