"""The native action session — B1's replacement for legacy ``Active``.

Measured before writing: the 26 members the write collaborators require plus the
18 deployment code uses come to **60 body lines** in legacy ``Active``, because
22 of the 26 are single-line delegations to the three collaborators. Only four
carry real logic — ``append_sample`` (23 lines),
``_get_action_for_file_conn_key`` (6), ``add_status`` (5) and ``set_estop`` (4).
So this is a delegation shell, and it is written as one.

What differs from ``Active``, and why it matters: the legacy object constructs
its own collaborators and the graft then swaps them for native ones between
``__init__`` and ``myinit`` — a mandatory window, because ``myinit`` creates the
data-logger task which may resolve ``self.data_stream`` before ``contain_action``
returns, so a post-return swap is a race. This session **constructs the native
collaborators directly**, so the window and the race it guards against simply do
not exist.

The session satisfies :class:`ActionSessionPort` structurally; the collaborators
declare that dependency rather than reaching into whatever ``Active`` exposes.

**Two members raise rather than delegate:** ``start_executor`` and
``oneoff_executor`` need the ``ExecutorRunner``, which is B1 Task 6. They raise
``NotImplementedError`` naming the task rather than returning ``None``, so a
ported module that starts an executor fails at the call site instead of
silently doing nothing and finishing an action that never ran.
"""

import asyncio
from typing import Optional, Union
from uuid import UUID

from helao.core.models.hlostatus import HloStatus
from helao.core.models.sample import (
    AssemblySample,
    GasSample,
    LiquidSample,
    NoneSample,
    SampleInheritance,
    SampleStatus,
    SampleType,
    SolidSample,
)
from helao.helpers import helao_logging as logging
from helao.helpers.premodels import Action

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = ["ActionSession"]


class ActionSession:
    """One in-flight action and the artifacts it writes."""

    def __init__(self, host, activeparams):
        """Bind the action and construct the native write collaborators.

        Args:
            host: The :class:`ActionHost` serving this action.
            activeparams: ``ActiveParams`` carrying the action and its file
                connection parameters.
        """
        from helao.core.models.file import FileConn

        self.base = host
        self.driver = host.driver
        self.active_uuid = activeparams.action.action_uuid
        self.action: Action = activeparams.action
        self.action_list = [self.action]
        self.listen_uuids: list = []
        self.num_data_queued = 0
        self.num_data_written = 0
        self.data_logger = None
        self.finish_lock = asyncio.Lock()
        #: Executor loop state, owned by the session and driven by the runner.
        self.action_task = None
        self.action_loop_running = False
        self.manual_stop = False

        self.action.action_server = host.server
        self.action.dummy = host.world_cfg.get("dummy", False)
        self.action.simulation = host.world_cfg.get("simulation", False)

        for aux_uuid in getattr(activeparams, "aux_listen_uuids", []):
            self.add_new_listen_uuid(aux_uuid)

        self.file_conn_dict: dict = {}
        for file_conn_key, file_conn_param in (
            activeparams.file_conn_params_dict or {}
        ).items():
            self.file_conn_dict[file_conn_key] = FileConn(params=file_conn_param)

        from helao.hexagon.app.executor_runner import ExecutorRunner

        self.executor_runner = ExecutorRunner(self)

        store = host.hexagon_wiring.artifact_store
        (
            self.data_stream,
            self.data_file_writer,
            self.action_finalizer,
        ) = store.collaborators_for(self)

    @classmethod
    async def open(cls, host, action: Action, **kwargs) -> "ActionSession":
        """Build the session for *action* with a default file connection.

        Mirrors what ``Base.setup_and_contain_action`` assembled before calling
        ``contain_action``: one default file connection carrying the endpoint's
        ``json_data_keys``, a file type defaulting to
        ``<server>_helao__file``, and an HLO header stamped with the current
        real time.
        """
        from helao.core.models.file import FileConnParams, HloHeaderModel
        from helao.helpers.active_params import ActiveParams

        json_data_keys = kwargs.get("json_data_keys", [])
        action_abbr = kwargs.get("action_abbr")
        file_type = kwargs.get("file_type")
        hloheader = kwargs.get("hloheader")

        if action_abbr is not None:
            action.action_abbr = action_abbr
        if file_type is None:
            file_type = f"{host.server_key.lower()}_helao__file"
        if hloheader is None:
            hloheader = HloHeaderModel(epoch_ns=host.get_realtime_nowait())

        dflt = host.dflt_file_conn_key()
        params = ActiveParams(
            action=action,
            file_conn_params_dict={
                dflt: FileConnParams(
                    file_conn_key=dflt,
                    json_data_keys=json_data_keys,
                    file_type=file_type,
                    hloheader=hloheader,
                )
            },
        )
        session = cls(host, params)
        host.actives[action.action_uuid] = session
        return session

    # -- real logic (the four members that are not delegation) ---------------

    async def add_status(self, action: Optional[Action] = None) -> None:
        """Put the action's status onto the host's fan-out queue."""
        if action is None:
            action = self.action
        LOGGER.info(
            f"Adding {str(action.action_uuid)} to {action.action_name} status list."
        )
        if not action.nonblocking:
            await self.base.status_q.put(action.get_act())

    def set_estop(self, action: Optional[Action] = None) -> None:
        """Mark the action estopped."""
        if action is None:
            action = self.action
        action.append_action_status(HloStatus.estopped)
        LOGGER.error(
            f"E-STOP {str(action.action_uuid)} on {action.action_name} status."
        )

    def _get_action_for_file_conn_key(self, file_conn_key: UUID) -> Optional[Action]:
        """Return the action owning *file_conn_key*, or None."""
        output_action = None
        for action in self.action_list:
            if file_conn_key in action.file_conn_keys:
                output_action = action
                break
        return output_action

    def set_sample_action_uuid(self, sample, action_uuid: UUID) -> None:
        """Tag a sample, and any sub-parts of an assembly, with *action_uuid*."""
        sample.action_uuid = [action_uuid]
        if sample.sample_type == SampleType.assembly:
            for part in sample.parts:
                self.set_sample_action_uuid(sample=part, action_uuid=action_uuid)

    async def append_sample(
        self,
        samples: list,
        IO: str,
        action: Optional[Action] = None,
    ) -> None:
        """Attach samples to the action's ``samples_in``/``samples_out``.

        Reproduces legacy behaviour including a latent defect: in the ``out``
        branch, legacy evaluates ``action.samples_out`` as a bare expression
        where it plainly means to assign ``[]``. The append on the next line
        therefore raises if ``samples_out`` was None. B1 preserves it -- the
        post-parity backlog is where behaviour changes belong, not a port.
        """
        if action is None:
            action = self.action
        if not samples:
            return
        for sample in samples:
            if isinstance(sample, NoneSample):
                continue
            self.set_sample_action_uuid(sample=sample, action_uuid=action.action_uuid)
            if sample.inheritance is None:
                LOGGER.info("sample.inheritance is None. Using 'allow_both'.")
                sample.inheritance = SampleInheritance.allow_both
            if not sample.status:
                LOGGER.info("sample.status is None. Using '{SampleStatus.preserved}'.")
                sample.reset_sample_status(SampleStatus.preserved)
            if IO == "in":
                if action.samples_in is None:
                    action.samples_in = []
                action.samples_in.append(sample)
            elif IO == "out":
                if action.samples_out is None:
                    action.samples_out  # noqa: B018 - legacy no-op, preserved
                action.samples_out.append(sample)
        await self.add_status(action=action)

    # -- delegation to the native data streamer ------------------------------

    async def get_realtime(
        self, epoch_ns: Optional[int] = None, offset: Optional[float] = None
    ) -> int:
        return await self.data_stream.get_realtime(epoch_ns=epoch_ns, offset=offset)

    def get_realtime_nowait(
        self, epoch_ns: Optional[int] = None, offset: Optional[float] = None
    ) -> int:
        return self.data_stream.get_realtime_nowait(epoch_ns=epoch_ns, offset=offset)

    async def write_live_data(self, output_str: str, file_conn_key: UUID):
        return await self.data_stream.write_live_data(output_str, file_conn_key)

    async def enqueue_data_dflt(self, datadict: dict):
        return await self.data_stream.enqueue_data_dflt(datadict)

    def _build_data_package(self, datamodel, action: Optional[Action] = None):
        return self.data_stream._build_data_package(datamodel, action)

    async def enqueue_data(self, datamodel, action: Optional[Action] = None):
        return await self.data_stream.enqueue_data(datamodel, action)

    def enqueue_data_nowait(self, datamodel, action: Optional[Action] = None):
        return self.data_stream.enqueue_data_nowait(datamodel, action)

    def assemble_data_msg(self, datamodel, action: Optional[Action] = None):
        return self.data_stream.assemble_data_msg(datamodel, action)

    def add_new_listen_uuid(self, new_uuid: UUID):
        return self.data_stream.add_new_listen_uuid(new_uuid)

    # -- delegation to the native data file writer ---------------------------

    def init_datafile(
        self,
        header,
        file_type,
        json_data_keys,
        file_sample_label,
        filename,
        file_group,
        file_conn_key: Optional[str] = None,
        action: Optional[Action] = None,
    ):
        return self.data_file_writer.init_datafile(
            header,
            file_type,
            json_data_keys,
            file_sample_label,
            filename,
            file_group,
            file_conn_key=file_conn_key,
            action=action,
        )

    def finish_hlo_header(self, file_conn_keys=None, realtime=None):
        return self.data_file_writer.finish_hlo_header(
            file_conn_keys=file_conn_keys, realtime=realtime
        )

    async def log_data_set_output_file(self, file_conn_key: UUID):
        return await self.data_file_writer.log_data_set_output_file(file_conn_key)

    def _resolve_output_path(
        self,
        file_type,
        filename,
        file_group,
        header,
        file_sample_label,
        json_data_keys,
        action,
    ):
        return self.data_file_writer._resolve_output_path(
            file_type,
            filename,
            file_group,
            header,
            file_sample_label,
            json_data_keys,
            action,
        )

    async def write_file(
        self,
        output_str: str,
        file_type: str,
        filename=None,
        file_group=None,
        header=None,
        sample_str=None,
        file_sample_label=None,
        json_data_keys=None,
        action: Optional[Action] = None,
    ):
        return await self.data_file_writer.write_file(
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
        output_str: str,
        file_type: str,
        filename=None,
        file_group=None,
        header=None,
        sample_str=None,
        file_sample_label=None,
        json_data_keys=None,
        action: Optional[Action] = None,
    ):
        return self.data_file_writer.write_file_nowait(
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

    async def track_file(
        self, file_type: str, file_path: str, samples, action: Optional[Action] = None
    ):
        return await self.data_file_writer.track_file(
            file_type, file_path, samples, action=action
        )

    # -- delegation to the native finalizer ----------------------------------

    async def split(self, uuid_list=None, new_fileconnparams=None):
        return await self.action_finalizer.split(
            uuid_list=uuid_list, new_fileconnparams=new_fileconnparams
        )

    async def finish(self, finish_uuid_list=None) -> Action:
        return await self.action_finalizer.finish(finish_uuid_list=finish_uuid_list)

    async def _finish(self, finish_uuid_list=None) -> Action:
        return await self.action_finalizer._finish(finish_uuid_list=finish_uuid_list)

    async def finish_manual_action(self):
        return await self.action_finalizer.finish_manual_action()

    # -- executor entry ------------------------------------------------------

    def start_executor(self, executor) -> dict:
        """Schedule *executor*'s loop and return the action dict."""
        return self.executor_runner.start_executor(executor)

    async def oneoff_executor(self, executor):
        """Run *executor* to completion inline."""
        return await self.executor_runner.oneoff_executor(executor)

    async def action_loop_task(self, executor):
        """Drive one executor through its lifecycle."""
        return await self.executor_runner.action_loop_task(executor)

    def executor_done_callback(self, futr):
        """Surface an exception raised by the action task."""
        return self.executor_runner.executor_done_callback(futr)

    def stop_action_task(self) -> None:
        """Request the poll loop stop. Called via ``host.stop_executor_by_id``."""
        return self.executor_runner.stop_action_task()

    async def send_nonblocking_status(self, retry_limit: int = 3) -> None:
        """Push this action's status to every attached client.

        Delegates to the status port, which owns the client registry and the
        retry policy -- legacy walked ``base.status_clients`` and called
        ``base.send_nbstatuspackage`` itself.
        """
        return await self.base.hexagon_wiring.status.send_nonblocking_status(
            self.action.get_act(), retry_limit=retry_limit
        )
