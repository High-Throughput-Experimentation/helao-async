"""Emergency-stop / error-clear collaborator extracted from ``Orch`` (CARDS P5b, cluster E).

``Orch.estop_loop``/``estop_actions``/``estop_finish_active``/``_estop_promote_all``/
``_estop_promote``/``clear_estop``/``clear_error`` implement the orchestrator's
emergency-stop lifecycle: fanning an ``estop`` out to every action server,
finalizing the in-flight experiment/sequence with ``estopped`` status so the
partial run is not left ``active`` in the run journal, handing those records to
the syncer, and the two
``clear_*`` endpoints that release the latch and resume. This module moves those
seven method bodies into an :class:`EstopController` collaborator that ``Orch``
delegates to.

Per the P5 constraints (:doc:`CARDS_REFACTOR_P5.md` sec 3.1 rule 3):
``EstopController`` caches no shared mutable state -- it holds only the ``orch``
back-reference and reads/writes ``globalstatusmodel``, ``active_experiment``,
``active_sequence``, ``last_experiment``/``last_sequence``, ``global_params``,
``current_stop_message``, ``active_run_id``, ``active_seq_exp_counter``,
``interrupt_q``, ``helaodirs``, ``ntp_offset`` and ``aloop`` through it at call
time, so a reassignment made between construction and a call (or between two
calls, e.g. by ``import_queues``) is always observed. Behavior is identical to
the original inline methods, including log wording and finalize/promote timing.

``async_action_dispatcher`` (estop fan-out) and ``move_dir`` (promotion) are
imported LAZILY from :mod:`helao.core.servers.orch` at call time -- the same
idiom :mod:`helao.core.servers.orch_dispatch` and
:mod:`helao.core.servers.orch_lifecycle` use -- so ``orch`` stays the single
module-global patch point the dispatch golden master rebinds.
"""

import asyncio
import traceback
from copy import deepcopy

from helao.core.models.action_start_condition import ActionStartCondition
from helao.core.models.hlostatus import HloStatus
from helao.core.models.orchstatus import LoopStatus
from helao.core.models.status_transitions import guarded_append, guarded_replace
from helao.helpers import helao_logging as logging
from helao.helpers.premodels import Action
from helao.helpers.time_utils import set_time

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

#: Per-server bound on the E-STOP dispatch. Above the server route's 2 s driver
#: bound plus the dispatcher's 3 s RPC probe. A server whose event loop is frozen
#: hangs its dispatch forever (the HTTP fallback has no total timeout), and
#: without this the finalization and alert after the fan-out never run.
ESTOP_SEND_TIMEOUT_S = 10.0


class EstopController:
    """Emergency-stop lifecycle and error-clear endpoints for an ``Orch``.

    Holds only the ``orch`` back-reference (never a cached deque/attribute/task
    handle), per the call-time state resolution rule -- see module docstring.
    """

    def __init__(self, orch):
        self.orch = orch

    async def estop_loop(self, reason: str = ""):
        """Emergency-stop the orchestrator and fan out an ``estop`` to every action server.

        Args:
            reason: Free-form text appended to the stop message and alert.
        """
        orch = self.orch
        reason_suffix = f"{' ' + reason if reason else ''}"
        LOGGER.info("estopping orch")

        # set globalstatusmodel.loop_state to estop
        orch.globalstatusmodel.loop_state = LoopStatus.estopped
        orch.active_run_id = None

        # force stop all running actions in the status dict (for this orch).
        # Route through the orch delegators (not the controller methods
        # directly) so this matches the original ``self.estop_actions`` /
        # ``self.estop_finish_active`` calls on ``Orch`` -- an instance-level
        # patch of ``orch.estop_actions`` stays observable here.
        # switch=True: every driver's ``estop(switch)`` acts only on True (stop
        # axes, motors off, outputs low), and the server latches its estop flag.
        # ``clear_estop`` sends switch=False to release the latch.
        await orch.estop_actions(switch=True)

        # reset loop intend
        await orch.intend_none()

        # finalize the active experiment/sequence with estopped status so the
        # partial run is evicted from the journal and handed to the syncer.
        # Nothing moves: the record stays where it was written.
        try:
            await orch.estop_finish_active()
        except Exception:
            LOGGER.error("error finalizing estopped experiment/sequence", exc_info=True)

        orch.current_stop_message = "E-STOP" + reason_suffix
        LOGGER.warning("E-STOP" + reason_suffix)
        LOGGER.alert("ORCH E-STOP")

    async def estop_actions(self, switch: bool):
        """Signal every registered action server to emergency-stop (or release).

        With ``switch=True`` each server's ``/estop`` endpoint calls the driver's
        estop, latches the server's estop flag, stops its executors and finalizes
        any in-flight actions with ``estopped`` status (finished in place via
        their normal lifecycle -- nothing moves). With ``switch=False`` it only
        calls the driver's release and clears the latch: it stops nothing and
        finalizes nothing, so work started after the E-STOP is left running. No
        placeholder ``estop`` action artifact is generated -- an idle server
        writes nothing, and estop is recorded purely through the ``*_status``
        fields of the actions (and, orch-side, the experiment/sequence) that were
        actually running.

        Args:
            switch: ``True`` to latch the per-server estop flag and let the
                driver act (``estop_loop`` sends this), ``False`` to release the
                latch (``clear_estop`` sends this).
        """
        # Lazy import so ``orch`` remains the single module-global patch point
        # the dispatch golden master rebinds (see module docstring).
        from helao.core.servers.orch import async_action_dispatcher

        orch = self.orch
        LOGGER.info(
            "estopping all servers" if switch else "releasing E-STOP on all servers"
        )

        async def _send(name: str, A: Action) -> None:
            try:
                # pass switch as an explicit query/RPC param so it reliably
                # reaches the endpoint's `switch` parameter
                _ = await asyncio.wait_for(
                    async_action_dispatcher(
                        orch.world_cfg, A, params={"switch": switch}
                    ),
                    ESTOP_SEND_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                LOGGER.error(
                    f"estop for {name} timed out after {ESTOP_SEND_TIMEOUT_S}s; "
                    f"continuing without it"
                )
            except Exception as e:
                tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                # no estop endpoint for this action server?
                LOGGER.error(f"estop for {name} failed with: {repr(e), tb,}")

        # Concurrent: one server that never answers must not starve the servers
        # after it of their E-STOP. The send lines are logged first, in
        # ``server_dict`` order.
        sends = []
        for actionservermodel in orch.globalstatusmodel.server_dict.values():
            # A minimal estop action -- the endpoint ignores the action payload
            # entirely now (it operates on whatever actions were already running),
            # so no experiment/sequence identity needs to be attached.
            A = Action(
                action_name="estop",
                action_server=actionservermodel.action_server.as_dict(),
                action_params={"switch": switch},
                start_condition=ActionStartCondition.no_wait,
            )
            name = actionservermodel.action_server.disp_name()
            LOGGER.info(f"Sending estop={switch} request to {name}")
            sends.append(_send(name, A))
        await asyncio.gather(*sends, return_exceptions=True)

    async def estop_finish_active(self):
        """Finalize the active experiment and sequence with estopped status on e-stop.

        The clean finish path (:meth:`finish_active_experiment` /
        :meth:`finish_active_sequence`) waits for all actions and is never reached
        on e-stop, so the active experiment and sequence would otherwise stay
        ``active`` in the run journal and never be enqueued for sync. This marks
        them ``estopped`` (leaving ``active`` swapped to ``finished`` so they read
        as terminal), persists the yml, and schedules a background handoff so the
        syncer can ship the partial run.

        It does NOT wait for actions inline: the e-stop already halted them and
        each action server finalizes its own in-flight actions independently
        (they may live on other machines). Nor does the background handoff wait
        for co-located child directories -- see :meth:`_estop_promote`.
        """
        orch = self.orch

        def _mark_estopped(status_list: list, owner: str):
            # Only swap active->finished when active is actually present:
            # ``guarded_replace`` appends the replacement when the old status is
            # absent, so an unguarded call on a second invocation (or a record
            # that never went active) would plant a phantom duplicate
            # 'finished'. The append is likewise guarded, making the whole
            # helper idempotent across a double-invoke.
            if HloStatus.active in status_list:
                guarded_replace(
                    status_list,
                    HloStatus.active,
                    HloStatus.finished,
                    owner=owner,
                )
            if HloStatus.estopped not in status_list:
                guarded_append(status_list, HloStatus.estopped, owner=owner)

        exp_to_move = None
        seq_to_move = None

        # Serialized with the clean finish paths; see ``RunLifecycle``. Nothing
        # inside awaits the clean paths, so the non-reentrant lock cannot deadlock.
        async with orch.finalize_lock:
            exp = orch.active_experiment
            seq = orch.active_sequence

            if exp is not None:
                _mark_estopped(exp.experiment_status, owner="experiment_status")
                exp.experiment_finished_timestamp = set_time(offset=orch.ntp_offset)
                exp.finished_global_params = {
                    k: v
                    for k, v in orch.global_params.items()
                    if k != "_fast_samples_in"
                }
                try:
                    if seq is not None:
                        # replace, don't duplicate, an entry a clean finish
                        # that died part-way already appended
                        ids = [e.experiment_uuid for e in seq.dispatched_experiments]
                        if exp.experiment_uuid in ids:
                            seq.dispatched_experiments[
                                ids.index(exp.experiment_uuid)
                            ] = deepcopy(exp.get_exp())
                        else:
                            seq.dispatched_experiments.append(deepcopy(exp.get_exp()))
                        await orch.write_active_sequence_seq()
                    await orch.write_exp(exp)
                except Exception:
                    LOGGER.error("error writing estopped experiment", exc_info=True)
                orch.last_experiment = deepcopy(exp)
                exp_to_move = orch.last_experiment
                orch.active_experiment = None

            if seq is not None:
                _mark_estopped(seq.sequence_status, owner="sequence_status")
                seq.sequence_finished_timestamp = set_time(offset=orch.ntp_offset)
                try:
                    await orch.write_seq(seq)
                except Exception:
                    LOGGER.error("error writing estopped sequence", exc_info=True)
                orch.last_sequence = deepcopy(seq)
                seq_to_move = orch.last_sequence
                orch.active_sequence = None
                orch.active_seq_exp_counter = 0
                orch.globalstatusmodel.counter_dispatched_actions = {}
                # The queued experiments (unpacked from this sequence only; other
                # sequences wait in ``sequence_dq``) and their expanded actions
                # belong to the sequence just finalized. With ``active_sequence``
                # gone they can never dispatch, and would crash the next start.
                n_exps, n_acts = len(orch.experiment_dq), len(orch.action_dq)
                orch.experiment_dq.clear()
                orch.action_dq.clear()
                if n_exps or n_acts:
                    LOGGER.warning(
                        f"E-STOP dropped {n_exps} queued experiment(s) and {n_acts} "
                        "queued action(s) belonging to the estopped sequence"
                    )

        # Hand off in a background task, experiment before sequence, so the
        # child record is journalled done (and enqueued) before its parent.
        if exp_to_move is not None or seq_to_move is not None:
            orch.aloop.create_task(self._estop_promote_all(exp_to_move, seq_to_move))

    async def _estop_promote_all(self, exp_to_move, seq_to_move):
        """Hand an estopped experiment then sequence to the syncer, in order."""
        if exp_to_move is not None:
            await self._estop_promote(exp_to_move, "experiment")
        if seq_to_move is not None:
            await self._estop_promote(seq_to_move, "sequence")

    async def _estop_promote(self, hobj, kind: str) -> bool:
        """Evict an estopped exp/seq from the run journal and hand it to the syncer.

        This used to wait up to 30s for the record's child directories to be
        vacated before calling :func:`move_dir`, and to give up (returning
        ``False``, without calling it) if they did not clear. That was correct
        while ``move_dir`` promoted only an exp/seq's *top-level* files and then
        ``rmtree``d the whole directory: moving while a co-located child action
        was still finalizing would have deleted that action's data.

        ``move_dir`` deletes nothing now -- it appends a ``done`` line to this
        server's run journal and hands the yml to the syncer -- so the wait
        guarded a hazard that no longer exists. Worse, under the unified
        ``RUNS`` tree a child action directory never goes away, so the wait
        could only ever time out, and the timeout path skipped the journal
        eviction *and* the syncer handoff: the record stayed ``active`` for the
        life of the station, and ``has_pending_work()`` reads exactly that set
        (plan A34, same shape as D-B/D-C).

        The child-still-running concern lives where it belongs: ``sync_yml``
        gates on a child's *sync status*, and treats an estopped active child
        as terminal rather than waiting on it forever.

        Returns:
            True if the record was handed off, False if ``move_dir`` raised.
        """
        # Lazy import so ``orch`` remains the single module-global patch point
        # the dispatch golden master rebinds (see module docstring).
        from helao.core.servers.orch import move_dir

        try:
            await move_dir(hobj, base=self.orch)
            return True
        except Exception:
            LOGGER.error(f"error handing estopped {kind} to the syncer", exc_info=True)
            return False

    async def clear_estop(self):
        """Clear estopped UUIDs, release the estop on every action server, and resume to ``stopped``."""
        orch = self.orch
        # which were estopped first
        LOGGER.info("clearing estopped uuids")
        orch.globalstatusmodel.clear_in_finished(hlostatus=HloStatus.estopped)
        # release estop for all action servers (via the orch delegator, matching
        # the original ``self.estop_actions`` call so instance patches apply)
        await orch.estop_actions(switch=False)
        # set orch status from estop back to stopped
        orch.globalstatusmodel.loop_state = LoopStatus.stopped
        await orch.interrupt_q.put("cleared_estop")

    async def clear_error(self):
        """Clear errored UUIDs from the finished dict and signal the interrupt queue."""
        orch = self.orch
        # currently only resets the error dict
        LOGGER.info("clearing errored uuids")
        orch.globalstatusmodel.clear_in_finished(hlostatus=HloStatus.errored)
        await orch.interrupt_q.put("cleared_errored")
