"""Emergency-stop / error-clear collaborator extracted from ``Orch`` (CARDS P5b, cluster E).

``Orch.estop_loop``/``estop_actions``/``estop_finish_active``/``_estop_promote_all``/
``_estop_promote``/``clear_estop``/``clear_error`` implement the orchestrator's
emergency-stop lifecycle: fanning an ``estop`` out to every action server,
finalizing the in-flight experiment/sequence with ``estopped`` status so the
partial run is not stranded in ``RUNS_ACTIVE``, promoting those records to
``RUNS_FINISHED`` once their co-located child action dirs clear, and the two
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

import os
import asyncio
import traceback
from copy import deepcopy

from helao.helpers import helao_logging as logging
from helao.helpers.premodels import Action
from helao.helpers.time_utils import set_time
from helao.core.models.action_start_condition import ActionStartCondition
from helao.core.models.hlostatus import HloStatus
from helao.core.models.orchstatus import LoopStatus
from helao.core.models.status_transitions import guarded_append, guarded_replace

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER


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
        await orch.estop_actions(switch=False)  # don't latch actionserver model

        # reset loop intend
        await orch.intend_none()

        # finalize + move the active experiment/sequence with estopped status so
        # the partial run is not stranded in RUNS_ACTIVE and can be synced
        try:
            await orch.estop_finish_active()
        except Exception:
            LOGGER.error("error finalizing estopped experiment/sequence", exc_info=True)

        orch.current_stop_message = "E-STOP" + reason_suffix
        LOGGER.warning("E-STOP" + reason_suffix)
        LOGGER.alert("ORCH E-STOP")

    async def estop_actions(self, switch: bool):
        """Signal every registered action server to emergency-stop (or release).

        Each server's ``/estop`` endpoint stops its executors and finalizes any
        in-flight actions with ``estopped`` status (moving them to
        ``RUNS_FINISHED`` via their normal lifecycle). No placeholder ``estop``
        action artifact is generated -- an idle server writes nothing, and estop
        is recorded purely through the ``*_status`` fields of the actions (and,
        orch-side, the experiment/sequence) that were actually running.

        Args:
            switch: ``True`` to latch the per-server estop flag, ``False`` to
                release it. Finalization of in-flight actions happens regardless;
                on release there are simply none left to finalize.
        """
        # Lazy import so ``orch`` remains the single module-global patch point
        # the dispatch golden master rebinds (see module docstring).
        from helao.core.servers.orch import async_action_dispatcher

        orch = self.orch
        LOGGER.info("estopping all servers")

        for (
            action_server_key,
            actionservermodel,
        ) in orch.globalstatusmodel.server_dict.items():
            # A minimal estop action -- the endpoint ignores the action payload
            # entirely now (it operates on whatever actions were already running),
            # so no experiment/sequence identity needs to be attached.
            A = Action(
                action_name="estop",
                action_server=actionservermodel.action_server.as_dict(),
                action_params={"switch": switch},
                start_condition=ActionStartCondition.no_wait,
            )
            LOGGER.info(
                f"Sending estop={switch} request to {actionservermodel.action_server.disp_name()}"
            )
            try:
                # pass switch as an explicit query/RPC param so it reliably
                # reaches the endpoint's `switch` parameter
                _ = await async_action_dispatcher(
                    orch.world_cfg, A, params={"switch": switch}
                )
            except Exception as e:
                tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                # no estop endpoint for this action server?
                LOGGER.error(
                    f"estop for {actionservermodel.action_server.disp_name()} failed with: {repr(e), tb,}"
                )

    async def estop_finish_active(self):
        """Finalize the active experiment and sequence with estopped status on e-stop.

        The clean finish path (:meth:`finish_active_experiment` /
        :meth:`finish_active_sequence`) waits for all actions and is never reached
        on e-stop, so the active experiment and sequence would otherwise stay
        stranded in ``RUNS_ACTIVE`` and never be enqueued for sync. This marks
        them ``estopped`` (leaving ``active`` swapped to ``finished`` so they read
        as terminal), persists the yml, and schedules a background promotion to
        ``RUNS_FINISHED`` so the syncer can ship the partial run.

        It does NOT wait for actions inline: the e-stop already halted them and
        each action server finalizes its own in-flight actions independently
        (they may live on other machines). The background promotion, however,
        does wait for co-located child directories to clear before moving -- see
        :meth:`_estop_promote`.
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

        if orch.active_experiment is not None:
            _mark_estopped(
                orch.active_experiment.experiment_status, owner="experiment_status"
            )
            orch.active_experiment.experiment_finished_timestamp = set_time(
                offset=orch.ntp_offset
            )
            orch.active_experiment.finished_global_params = {
                k: v for k, v in orch.global_params.items() if k != "_fast_samples_in"
            }
            try:
                if orch.active_sequence is not None:
                    orch.active_sequence.dispatched_experiments.append(
                        deepcopy(orch.active_experiment.get_exp())
                    )
                    await orch.write_active_sequence_seq()
                await orch.write_exp(orch.active_experiment)
            except Exception:
                LOGGER.error("error writing estopped experiment", exc_info=True)
            orch.last_experiment = deepcopy(orch.active_experiment)
            exp_to_move = orch.last_experiment
            orch.active_experiment = None

        if orch.active_sequence is not None:
            _mark_estopped(
                orch.active_sequence.sequence_status, owner="sequence_status"
            )
            orch.active_sequence.sequence_finished_timestamp = set_time(
                offset=orch.ntp_offset
            )
            try:
                await orch.write_seq(orch.active_sequence)
            except Exception:
                LOGGER.error("error writing estopped sequence", exc_info=True)
            orch.last_sequence = deepcopy(orch.active_sequence)
            seq_to_move = orch.last_sequence
            orch.active_sequence = None
            orch.active_seq_exp_counter = 0
            orch.globalstatusmodel.counter_dispatched_actions = {}

        # Promote in a background task, experiment before sequence, so the
        # sequence dir's child experiment dir is gone before the sequence moves.
        if exp_to_move is not None or seq_to_move is not None:
            orch.aloop.create_task(self._estop_promote_all(exp_to_move, seq_to_move))

    async def _estop_promote_all(self, exp_to_move, seq_to_move):
        """Promote an estopped experiment then sequence to RUNS_FINISHED, in order."""
        if exp_to_move is not None:
            await self._estop_promote(exp_to_move, "experiment")
        if seq_to_move is not None:
            await self._estop_promote(seq_to_move, "sequence")

    async def _estop_promote(self, hobj, kind: str, max_wait: int = 30) -> bool:
        """Move an estopped exp/seq to RUNS_FINISHED once its child dirs have cleared.

        :func:`move_dir` promotes only an exp/seq's *top-level* files and then
        ``rmtree``s the whole directory, so moving while a co-located child
        action is still finalizing in ``RUNS_ACTIVE`` would delete that action's
        data. We wait (bounded) for child subdirectories to be vacated by the
        (possibly co-located) action servers; if they don't clear, we leave the
        record in ``RUNS_ACTIVE`` (data preserved) rather than destroy in-flight
        children -- ``finish_pending`` can promote it later. For remote action
        servers there are no local child dirs, so this returns immediately.

        Returns:
            True if the record was moved, False if left in place.
        """
        # Lazy import so ``orch`` remains the single module-global patch point
        # the dispatch golden master rebinds (see module docstring).
        from helao.core.servers.orch import move_dir

        orch = self.orch
        save_dir = str(orch.helaodirs.save_root)
        subdir = (
            hobj.get_experiment_dir()
            if kind == "experiment"
            else hobj.get_sequence_dir()
        )
        ydir = os.path.normpath(os.path.join(save_dir, subdir))

        def _child_dirs():
            if not os.path.isdir(ydir):
                return []
            return [e.path for e in os.scandir(ydir) if e.is_dir()]

        waited = 0
        while _child_dirs() and waited < max_wait:
            await asyncio.sleep(1)
            waited += 1
        remaining = _child_dirs()
        if remaining:
            LOGGER.warning(
                f"estop: {kind} {ydir} still has {len(remaining)} child dir(s) in "
                f"RUNS_ACTIVE after {max_wait}s; leaving it in place (data "
                f"preserved) to avoid deleting in-flight child actions. Run "
                f"finish_pending once children clear to sync it."
            )
            return False
        try:
            await move_dir(hobj, base=orch)
            return True
        except Exception:
            LOGGER.error(
                f"error moving estopped {kind} to RUNS_FINISHED", exc_info=True
            )
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
