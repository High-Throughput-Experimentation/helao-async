"""Native action finalizer (hexagon P2b-1).

Verbatim re-body of the CARDS-P6 ``ActionFinalizer`` collaborator
(``helao/core/servers/active_finalizer.py``) — the finish / split /
substitute close-out state machine, including the ce846da1 join-drain-close
chain: send finished data_stream packets (<=5 x 0.1 s), wait
``num_data_queued <= num_data_written`` (<=5 x 0.1 s), THEN close every file
handle and cancel ``data_logger`` (late data beyond the bounded retries is
dropped exactly as legacy drops it); HLO post-processors may rewrite
``files[]``; final ``write_act`` per action; fire-and-forget ``move_dir``
promotion for non-manual actions only; ``finish_manual_action`` synthesizes
the ``exp--``/``seq--`` metas. Method bodies are byte-identical to legacy
(source-parity-pinned by ``test_native_finalizer.py``); only this docstring,
the class name, and ``__all__`` differ.

Per-Active collaborator: holds only the ``active`` back-reference; the drain
counters (``num_data_queued``/``num_data_written``), ``action_list``,
``file_conn_dict``, ``data_logger`` and ``finish_lock`` are read live off
``Active`` at call time -- caching ANY of them here recreates the exact
ce846da1 failure class (a finish that closes before late data lands, a
leaked handle -> WinError 32 -> permanent promotion failure). Swapped in for
``active.action_finalizer`` by ``graft_active_write_path`` between
``Active.__init__`` and ``myinit()``.

Module-global functions ``set_time`` / ``move_dir`` /
``async_private_dispatcher`` are imported here exactly as the legacy module
imports them; tests patch them on THIS module (the same seam the legacy
golden master patches on ``active_finalizer``/``base``).
"""

import asyncio
import os
from copy import copy, deepcopy
from typing import Optional
from uuid import UUID

from helao.core.error import ErrorCodes
from helao.core.models.data import DataModel
from helao.core.models.file import FileConn, FileConnParams
from helao.core.models.hlostatus import HloStatus
from helao.core.models.run_dir import RunDir
from helao.helpers import helao_logging as logging
from helao.helpers.dispatcher import async_private_dispatcher
from helao.helpers.premodels import Action
from helao.helpers.time_utils import set_time
from helao.helpers.yml_tools import move_dir
from helao.hexagon.ports.action_session import ActionSessionPort

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = ["NativeActionFinalizer"]


class NativeActionFinalizer:
    """Native drop-in for ``active.action_finalizer`` (legacy surface, native body).

    Holds only the ``active`` back-reference (never cached counter/list/conn
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

    async def split_and_keep_active(self):
        """Split the current action while leaving every previous action open."""
        await self.active.split(uuid_list=[])

    async def split_and_finish_prev_uuids(self):
        """Split the current action and finish every previously held action."""
        await self.active.split(uuid_list=None)

    async def finish_all(self):
        """Finish every action tracked by this active wrapper."""
        await self.active.finish(finish_uuid_list=None)

    async def split(
        self,
        uuid_list: Optional[list[UUID]] = None,
        new_fileconnparams: Optional[FileConnParams] = None,
    ) -> list[UUID]:
        """Fork the current action into a new sibling with fresh file connections.

        The previous action is marked split, a new action UUID is generated,
        new file connections are opened (copying the prior parameters unless
        ``new_fileconnparams`` is provided), and either all or a chosen subset
        of prior actions are finished.

        Args:
            uuid_list: UUIDs to finish; ``None`` finishes all except the new one.
            new_fileconnparams: Optional parameters for the new file connections.

        Returns:
            The keys of the newly created file connections.
        """

        try:
            new_file_conn_keys = []

            LOGGER.info("got split action request")
            # add split status to current action
            if HloStatus.split not in self.active.action.action_status:
                self.active.action.append_action_status(HloStatus.split)
            # make a copy of prev_action
            prev_action = deepcopy(self.active.action)
            prev_action_list = deepcopy(self.active.action_list)
            # set the data_stream_status
            prev_action.data_stream_status = HloStatus.split
            self.active.action.data_stream_status = HloStatus.active
            # increase split counter for new action
            # needs to happen before init_act
            # as its also used in the fodler name
            self.active.action.action_split += 1

            # now re-init current action
            # force action init (new action uuid and timestamp)
            self.active.action.init_act(time_offset=self.active.base.ntp_offset, force=True)
            self.active.action_list += prev_action_list
            # add new action uuid to listen_uuids
            self.active.add_new_listen_uuid(self.active.action.action_uuid)
            # remove previous listen_uuid to stop writing to previous hlo file
            self.active.listen_uuids.remove(prev_action.action_uuid)

            # add child and parent action uuids
            prev_action.child_action_uuid = self.active.action.action_uuid
            self.active.action.parent_action_uuid = prev_action.action_uuid

            # reset action sample list and others
            self.active.action.samples_in = []
            self.active.action.samples_out = []
            self.active.action.child_action_uuid = None
            self.active.action.files = []

            # reset all of the new actions file_conn uuids
            self.active.action.file_conn_keys = []

            # grab all fileconns from prev_action
            # some action are multi file out and each split action
            # needs to create the same number of new files
            for file_conn_key in prev_action.file_conn_keys:
                # await asyncio.sleep(0.1)
                LOGGER.info("Creating new file_conn for split action")
                current_epoch_ns = await self.active.get_realtime()
                new_file_conn_key = self.active.base.new_file_conn_key(
                    key=str(current_epoch_ns)
                )
                if new_fileconnparams is None:
                    # get last file conn
                    new_file_conn = self.active.file_conn_dict[file_conn_key].deepcopy()
                    # modify last file_conn
                    new_file_conn.params.file_conn_key = new_file_conn_key
                    # reset some of the file conn parameters
                    new_file_conn.reset_file_conn()
                    # add new timestamp
                    new_file_conn.params.hloheader.epoch_ns = current_epoch_ns
                else:
                    new_file_conn = FileConn(params=new_fileconnparams)
                    new_file_conn.params.file_conn_key = new_file_conn_key

                new_file_conn_keys.append(new_file_conn_key)
                # add the new one to active file conn dict
                self.active.file_conn_dict[new_file_conn.params.file_conn_key] = new_file_conn
                # and add the new file_conn_uuid to the new split action
                self.active.action.file_conn_keys = [
                    new_file_conn.params.file_conn_key
                ] + self.active.action.file_conn_keys
                self.active.num_data_queued = 0
                self.active.num_data_written = 0

            # TODO:
            # update other action settings?
            # - sample name

            # # prepend new action to previous action list
            # self.action_list.append(prev_action)

            # send status for new split action
            await self.active.add_status()

            # finish selected actions
            if uuid_list is None:
                # default: finish all except current one
                await self.active.finish(
                    finish_uuid_list=[act.action_uuid for act in self.active.action_list[1:]]
                )

            else:
                # use the supplied uuid list
                await self.active.finish(finish_uuid_list=uuid_list)
        except Exception:
            LOGGER.error("Active.split() failed", exc_info=True)

        return new_file_conn_keys

    async def substitute(self):
        """Close every open HLO file for this active so a new active can take over."""
        for filekey in self.active.file_conn_dict:
            if self.active.file_conn_dict[filekey].file:
                await self.active.file_conn_dict[filekey].file.close()

    async def finish(
        self,
        finish_uuid_list: Optional[list[UUID]] = None,
        # end_state: HloStatus = HloStatus.finished
    ) -> Action:
        """Finalize the listed actions (or all of them) and clean up file/data resources.

        Exports global parameters, drains the data queue, runs HLO
        post-processors, closes file connections, schedules the run directory
        move, and broadcasts the final status for each finished action.

        Serialized via ``finish_lock`` so the action loop and a driver polling
        loop cannot run finalization (and its ``write_act``) concurrently for
        the same active.

        Args:
            finish_uuid_list: UUIDs to finish; ``None`` finishes every action.

        Returns:
            The current ``self.action`` after finalisation.
        """
        async with self.active.finish_lock:
            return await self.active._finish(finish_uuid_list=finish_uuid_list)

    async def _finish(
        self,
        finish_uuid_list: Optional[list[UUID]] = None,
    ) -> Action:
        """Finalization body for :meth:`finish`; must be called under ``finish_lock``."""
        if finish_uuid_list is None:
            finish_uuid_list = [action.action_uuid for action in self.active.action_list]

        for action in self.active.action_list:
            if action.action_uuid not in finish_uuid_list:
                continue
            if HloStatus.finished in action.action_status:
                continue

            try:
                # set status to finish
                # (replace active with finish)
                action.replace_action_status(HloStatus.active, HloStatus.finished)
                action.action_finished_timestamp = set_time(offset=self.active.base.ntp_offset)

                if action.error_code != ErrorCodes.none:
                    if HloStatus.errored not in action.action_status:
                        action.append_action_status(HloStatus.errored)

                # send globalparams
                if action.to_global_params:
                    export_params = {}
                    if isinstance(action.to_global_params, list):
                        for k in action.to_global_params:
                            if k in action.action_params:
                                LOGGER.info(f"updating {k} in orch global vars")
                                export_params[k] = action.action_params[k]
                            elif k in action.action_output:
                                LOGGER.info(f"updating {k} in orch global vars")
                                export_params[k] = action.action_output[k]
                            else:
                                LOGGER.info(
                                    f"key {k} not found in action output or params"
                                )
                    elif isinstance(action.to_global_params, dict):
                        for k1, k2 in action.to_global_params.items():
                            if k1 in action.action_params:
                                LOGGER.info(f"updating {k2} in global vars")
                                export_params[k2] = action.action_params[k1]
                            elif k1 in action.action_output:
                                LOGGER.info(f"updating {k2} in global vars")
                                export_params[k2] = action.action_output[k1]
                            else:
                                LOGGER.info(
                                    f"key {k1} not found in action output or params"
                                )
                    # Skip the RPC when nothing resolved (e.g. an estop interrupts
                    # before the action produces its to_global_params output): an
                    # empty json_dict reaches update_global_params with no args and
                    # its required `params` cannot be filled -> TypeError. An empty
                    # update is a no-op anyway.
                    if export_params:
                        _, error_code = await async_private_dispatcher(
                            server_key=action.orch_key,
                            host=action.orch_host,
                            port=action.orch_port,
                            private_action="update_global_params",
                            json_dict=export_params,
                        )
                        if error_code == ErrorCodes.none:
                            LOGGER.info("Successfully updated global params.")
            except Exception:
                LOGGER.error(
                    f"Failed to update global params for action {action.action_uuid}",
                    exc_info=True,
                )

        # check if all actions are fininshed
        # if yes close dataLOGGER etc
        all_finished = True
        for action in self.active.action_list:
            if HloStatus.finished not in action.action_status:
                # at least one is not finished
                all_finished = False
                break

        if all_finished:
            LOGGER.info("finish active: sending finish data_stream_status package")
            retry_counter = 0
            while (
                not all(
                    [
                        action.data_stream_status != HloStatus.active
                        for action in self.active.action_list
                    ]
                )
                and retry_counter < 5
            ):
                try:
                    await self.active.enqueue_data(
                        datamodel=DataModel(
                            data={}, errors=[], status=HloStatus.finished
                        )
                    )
                    LOGGER.debug(
                        f"Waiting for data_stream finished package: {[action.data_stream_status for action in self.active.action_list]}"
                    )
                    await asyncio.sleep(0.1)
                except Exception:
                    LOGGER.error(
                        "Failed to enqueue finished data stream package",
                        exc_info=True,
                    )
                retry_counter += 1

            LOGGER.debug("checking if all queued data has written.")
            write_retries = 5
            write_iter = 0
            while (
                self.active.num_data_queued > self.active.num_data_written
                and write_iter < write_retries
            ):
                try:
                    LOGGER.info(
                        f"num_queued {self.active.num_data_queued} > num_written {self.active.num_data_written}, sleeping for 0.1 second."
                    )
                    for action in self.active.action_list:
                        if action.data_stream_status != HloStatus.active:
                            await self.active.enqueue_data(
                                datamodel=DataModel(
                                    data={}, errors=[], status=HloStatus.finished
                                )
                            )
                            LOGGER.info(
                                f"Setting datastream to finished: {action.data_stream_status}"
                            )
                except Exception:
                    LOGGER.error(
                        "Failed to requeue finished data stream package",
                        exc_info=True,
                    )
                write_iter += 1
                await asyncio.sleep(0.1)

            try:
                # self.action_list[-1] is the very first action
                if self.active.action_list[-1].manual_action:
                    await self.active.finish_manual_action()

                # all actions are finished
                LOGGER.debug("finishing data logging.")
                for filekey in self.active.file_conn_dict:
                    if self.active.file_conn_dict[filekey].file:
                        await self.active.file_conn_dict[filekey].file.close()
                self.active.file_conn_dict = {}

                # finish the data writer
                self.active.data_logger.cancel()
            except Exception:
                LOGGER.error("Failed to finish data logging", exc_info=True)

            save_root = str(self.active.base.helaodirs.save_root)
            if self.active.action.manual_action:
                save_root = save_root.replace(RunDir.ACTIVE.value, RunDir.DIAG.value)
            try:
                # call custom hlo post-processor if it exists
                if self.active.base.hlo_postprocessors:
                    for hpp, libname in zip(
                        self.active.base.hlo_postprocessors, self.active.base.hlo_postprocess_libs
                    ):
                        LOGGER.info(
                            f"Running custom HLO post-processor: {os.path.basename(libname).split('.py')[0]}"
                        )
                        loop = asyncio.get_running_loop()
                        postprocessor = hpp(self.active.action, save_root)
                        updated_file_list = await loop.run_in_executor(
                            None, postprocessor.process
                        )
                        self.active.action.files = updated_file_list
            except Exception:
                LOGGER.error("Failed to run custom HLO post-processor", exc_info=True)
            try:
                l10 = self.active.base.actives.pop(self.active.active_uuid, None)
                if l10 is not None:
                    self.active.base.history[l10.action.action_uuid] = copy(l10.action)
            except Exception:
                LOGGER.error(
                    "Failed to remove active from base.actives or last_10_active",
                    exc_info=True,
                )
            LOGGER.info("all active action are done, closing active")

            # DB server call to finish_yml if DB exists
            for action in self.active.action_list:
                try:
                    # write final act meta file (overwrite existing one)
                    await self.active.base.write_act(action=action)
                except Exception:
                    LOGGER.error(
                        f"Failed to write act meta file for action {action.action_uuid}",
                        exc_info=True,
                    )
                try:
                    # send the last status
                    await self.active.add_status(action=action)
                except Exception:
                    LOGGER.error(
                        f"Failed to send last status for action {action.action_uuid}",
                        exc_info=True,
                    )
                if not self.active.action.manual_action:
                    try:
                        self.active.base.aloop.create_task(move_dir(action, base=self.active.base))
                        # pop from local action task queue
                    except Exception:
                        LOGGER.error(
                            f"Failed to move directory for action {action.action_uuid}",
                            exc_info=True,
                        )
                else:
                    LOGGER.info(
                        f"Action {action.action_uuid} is a manual action, skipping directory move."
                    )
                if action.action_uuid in self.active.base.local_action_task_queue:
                    self.active.base.local_action_task_queue.remove(action.action_uuid)

        return self.active.action

    async def finish_manual_action(self):
        """Finalize a manual action by writing its synthesized experiment and sequence meta files."""
        # self.action_list[-1] is the very first action
        if self.active.action_list[-1].manual_action:
            exp = deepcopy(self.active.action_list[-1])
            exp.reset_experiment_status(HloStatus.finished)
            exp.reset_sequence_status(HloStatus.finished)
            exp.samples_in = []
            exp.samples_out = []
            exp.files = []

            # add actions to experiment
            for action in self.active.action_list:
                exp.dispatched_actions.append(action.get_act())

            # add experiment to sequence
            exp.dispatched_experiments.append(action.get_exp())

            # this will write the correct
            # sequence and experiment meta files for
            # manual operation
            # create and write exp file for manual action
            await self.active.base.write_exp(exp)
            # create and write seq file for manual action
            await self.active.base.write_seq(exp)
