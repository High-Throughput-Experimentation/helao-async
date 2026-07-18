"""Reducer-command effect runner over a wrapped legacy Orch (P1b1 DD-1..DD-5).

Every effect is THIN DELEGATION onto the legacy Orch surface (behavior
identical by construction); the five marked commands re-read live state
immediately before executing (DD-3, spec §4.2.2 option (a)) — the same three
guard sites orch_dispatch.py carries. State deltas follow DD-2. Never issues
an RPC/HTTP call to its own server (KEEP #3)."""

import asyncio
from datetime import datetime
from typing import Optional
from uuid import UUID

from helao.helpers import helao_logging
from helao.hexagon.app.wiring import PortWiring
from helao.hexagon.domain.dispatch_policy import (
    DispatchPolicy,
    should_close_out_experiment,
    should_close_out_sequence,
)
from helao.hexagon.domain.models import (
    ErrorCodes,
    HloStatus,
    LoopIntent,
    LoopStatus,
    OrchStatus,
)
from helao.hexagon.domain.orchestration import (
    AlertOperator,
    ClearActionQueue,
    ClearActiveRunId,
    ClearErroredFromFinished,
    ClearEstoppedFromFinished,
    CloseOutExperimentCmd,
    CloseOutSequenceCmd,
    Command,
    CreateDispatchLoopTask,
    DispatchHeadAction,
    EstopFanout,
    ExportQueuesCmd,
    FinishActiveEstopped,
    FinishThenDispatchExperimentCmd,
    FinishThenDispatchSequenceCmd,
    InterruptWake,
    OrchestrationState,
    PruneDeadActions,
    RefuseStart,
    ReleaseServersEstop,
    RequeueHeadAction,
    RetryDriverHealth,
    SetStopMessage,
    WaitAllActionsIdle,
)


class _LazyServerLogger:
    """Resolves ``helao_logging.LOGGER`` at call time instead of binding a
    stdlib ``logging.getLogger(__name__)`` at import time: the latter always
    returns a real (but unrouted, unhandled) logger object, so it never
    raises -- it just silently drops every record instead of reaching
    ``<root>/LOGS/<server_key>.log``. Same call-time-resolution rationale as
    ``LegacyLoggingAdapter._log()`` (logging_adapter.py): the launcher installs
    the per-server singleton onto ``helao_logging.LOGGER`` after this module
    is imported, and bare unit tests never install it at all (``None``)."""

    def info(self, msg, *args, **kwargs):
        lg = helao_logging.LOGGER
        if lg is not None:
            lg.info(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        lg = helao_logging.LOGGER
        if lg is not None:
            lg.warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        lg = helao_logging.LOGGER
        if lg is not None:
            lg.error(msg, *args, **kwargs)


LOGGER = _LazyServerLogger()

__all__ = ["OrchCommandRunner", "apply_state_delta", "derive_state"]


def derive_state(orch) -> OrchestrationState:
    """Fresh live snapshot (call-time state resolution, DD-2)."""
    gsm = orch.globalstatusmodel
    return OrchestrationState(
        loop_state=gsm.loop_state,
        loop_intent=gsm.loop_intent,
        orch_state=gsm.orch_state,
        n_seqs=len(orch.sequence_dq),
        n_exps=len(orch.experiment_dq),
        n_acts=len(orch.action_dq),
        active_experiment_present=orch.active_experiment is not None,
        active_sequence_present=orch.active_sequence is not None,
        na_drivers=tuple(
            k for k, (_, v) in orch.status_summary.items() if v == "unknown"
        ),
        step_thru_actions=orch.step_thru_actions,
        step_thru_experiments=orch.step_thru_experiments,
        step_thru_sequences=orch.step_thru_sequences,
    )


async def apply_state_delta(
    orch,
    old: OrchestrationState,
    new: OrchestrationState,
    *,
    skip_loop_state: bool = False,
) -> None:
    """DD-2: state-first delta. loop_state guarded against concurrent E-STOP
    (only a transition whose INPUT state was estopped — T10 — may overwrite a
    live estopped value); T5 exception via skip_loop_state; loop_intent routed
    through the legacy intend_* methods (interrupt_q wake preserved);
    orch_state written back since P2a (the ingestion rebind removed the
    legacy StatusIngester's inline writers at the same instant — sole-writer
    property). The orch_state write is deliberately UNGUARDED against a live
    estopped value: the legacy inline chain always overwrote orch_state with
    idle/busy on any fold (its estop branch is started-guarded), so the
    reducer's StatusChanged must keep doing the same."""
    gsm = orch.globalstatusmodel
    if not skip_loop_state and new.loop_state != old.loop_state:
        live = gsm.loop_state
        if live == LoopStatus.estopped and old.loop_state != LoopStatus.estopped:
            LOGGER.info("concurrent E-STOP observed; loop_state write suppressed")
        else:
            gsm.loop_state = new.loop_state
    if new.orch_state != old.orch_state:
        gsm.orch_state = new.orch_state
    if new.loop_intent != old.loop_intent:
        intender = {
            LoopIntent.stop: orch.intend_stop,
            LoopIntent.skip: orch.intend_skip,
            LoopIntent.estop: orch.intend_estop,
            LoopIntent.none: orch.intend_none,
        }[new.loop_intent]
        await intender()


class OrchCommandRunner:
    def __init__(self, orch, wiring: PortWiring):
        self.orch = orch
        self.wiring = wiring
        self.policy = DispatchPolicy()
        # P2a: stringified uuids pruned by PruneDeadActions — the
        # DispatchHeadAction history poll's health-aware exit (Q3)
        self.pruned_uuids: set = set()

    async def execute(self, cmd: Command) -> Optional[ErrorCodes]:
        orch = self.orch
        gsm = orch.globalstatusmodel

        if isinstance(cmd, CreateDispatchLoopTask):
            return None  # owned by HexRuntime (wakes the parked loop task)

        if isinstance(cmd, RefuseStart):
            LOGGER.info(cmd.reason)
            return None

        if isinstance(cmd, DispatchHeadAction):
            # live re-check #1 (outer twin of the in-lock guard the wrapped
            # _dispatch_action_locked already carries)
            if gsm.loop_state == LoopStatus.estopped:
                return ErrorCodes.estop
            LOGGER.info("!!!checking conditions for next action")
            rc = await orch.loop_task_dispatch_action()
            # history poll (orch_dispatch.py:621-622) — ingestion registers
            # the uuid. P2a health-aware exit (Q3): a dead peer's pruned
            # uuid breaks the poll (the prune also registers history, so
            # either condition releases it).
            while orch.last_dispatched_action_uuid not in orch.action_history.keys():
                if str(orch.last_dispatched_action_uuid) in self.pruned_uuids:
                    break
                await asyncio.sleep(0.2)
            pause = self.policy.evaluate_step_thru(derive_state(orch).snapshot())
            if pause is not None:
                orch.current_stop_message = pause.reason
                LOGGER.warning(pause.reason)
                await orch.stop()
            return rc

        if isinstance(cmd, FinishThenDispatchExperimentCmd):
            if gsm.loop_state == LoopStatus.estopped:  # live re-check #2
                LOGGER.info(
                    "orchestrator estopped, not finishing/dispatching experiment"
                )
                return ErrorCodes.estop
            LOGGER.info(
                "!!!waiting for all actions to finish before dispatching next experiment"
            )
            LOGGER.info("finishing last experiment")
            await orch.finish_active_experiment()
            LOGGER.info("!!!dispatching next experiment")
            return await orch.loop_task_dispatch_experiment()

        if isinstance(cmd, FinishThenDispatchSequenceCmd):
            if gsm.loop_state == LoopStatus.estopped:  # live re-check #2
                LOGGER.info("orchestrator estopped, not finishing/dispatching sequence")
                return ErrorCodes.estop
            LOGGER.info(
                "!!!waiting for all actions to finish before dispatching next sequence"
            )
            LOGGER.info("finishing last sequence")
            await orch.finish_active_sequence()
            LOGGER.info("!!!dispatching next sequence")
            return await orch.loop_task_dispatch_sequence()

        if isinstance(cmd, RetryDriverHealth):
            # verbatim orch_dispatch._exec_driver_health (<=5 x 5 s)
            na_drivers = list(cmd.na_drivers)
            retries = 0
            while retries < 5 and na_drivers:
                LOGGER.info(
                    f"unknown driver states: {', '.join(na_drivers)}, "
                    "retrying in 5 seconds"
                )
                await asyncio.sleep(5)
                na_drivers = [
                    k for k, (_, v) in orch.status_summary.items() if v == "unknown"
                ]
                retries += 1
            if na_drivers:
                orch.current_stop_message = (
                    f"unknown driver states: {', '.join(na_drivers)}"
                )
                LOGGER.warning(orch.current_stop_message)
                await orch.stop()
            return None

        if isinstance(cmd, WaitAllActionsIdle):
            # verbatim DrainForStop body — OWNS the stopped write (DD-2 T5)
            LOGGER.info("stopping orchestrator")
            while gsm.loop_state != LoopStatus.stopped:
                await orch.orch_wait_for_all_actions()
                if gsm.orch_state == OrchStatus.idle:
                    await orch.intend_none()
                    LOGGER.info("got stop")
                    gsm.loop_state = LoopStatus.stopped
                    break
            return None

        if isinstance(cmd, RequeueHeadAction):
            # DD-4: unreachable in P1b1 (requeue lives inside the wrapped
            # dispatch fold); executing would double-insert — log loudly.
            LOGGER.warning(
                "RequeueHeadAction ignored in P1b1 wrapped-legacy composition"
            )
            return None

        if isinstance(cmd, ClearActionQueue):
            orch.action_dq.clear()
            return None

        if isinstance(cmd, SetStopMessage):
            orch.current_stop_message = cmd.message
            return None

        if isinstance(cmd, AlertOperator):
            self.wiring.require("logging")
            LOGGER.warning(cmd.message)
            self.wiring.logging.alert(cmd.message)  # type: ignore[union-attr]
            return None

        if isinstance(cmd, EstopFanout):
            await orch.estop_actions(switch=cmd.switch)
            return None

        if isinstance(cmd, ClearActiveRunId):
            orch.active_run_id = None
            return None

        if isinstance(cmd, FinishActiveEstopped):
            try:
                await orch.estop_finish_active()
            except Exception:
                LOGGER.error(
                    "error finalizing estopped experiment/sequence", exc_info=True
                )
            return None

        if isinstance(cmd, CloseOutExperimentCmd):
            if should_close_out_experiment(  # live re-check #3
                len(orch.action_dq),
                orch.active_experiment is not None,
                gsm.loop_state,
            ):
                LOGGER.info("finishing final experiment")
                await orch.finish_active_experiment()
            return None

        if isinstance(cmd, CloseOutSequenceCmd):
            if should_close_out_sequence(  # live re-check #3
                len(orch.experiment_dq),
                len(orch.action_dq),
                orch.active_sequence is not None,
                gsm.loop_state,
            ):
                LOGGER.info("finishing final sequence")
                await orch.finish_active_sequence()
            return None

        if isinstance(cmd, ExportQueuesCmd):
            if any(
                len(x) > 0
                for x in (orch.sequence_dq, orch.experiment_dq, orch.action_dq)
            ):
                orch.export_queues(timestamp_pck=cmd.timestamped)
            return None

        if isinstance(cmd, ClearEstoppedFromFinished):
            gsm.clear_in_finished(hlostatus=HloStatus.estopped)
            return None

        if isinstance(cmd, ClearErroredFromFinished):
            gsm.clear_in_finished(hlostatus=HloStatus.errored)
            return None

        if isinstance(cmd, ReleaseServersEstop):
            await orch.estop_actions(switch=False)
            return None

        if isinstance(cmd, InterruptWake):
            await orch.interrupt_q.put(cmd.message)
            return None

        if isinstance(cmd, PruneDeadActions):
            # item-6 dead-peer exit (Q3, pure-hexagon): move the dead
            # server's uuids out of EVERY active_dict (global + per-endpoint,
            # like /clear_actives — a global-only pop would be resurrected by
            # the next fold's _sort_status) into the finished bucket with a
            # terminal status, and register them in action_history so the
            # history poll and non-blank-history asserts hold. Runs WITHOUT
            # aiolock: fully synchronous on the event loop, and taking the
            # lock here would add a third owner (invariant: ingestion +
            # dispatch critical section only).
            from helao.hexagon.app.ingestion import action_history_meta

            now = datetime.now()
            for uuid_str in cmd.action_uuids:
                act_uuid = UUID(uuid_str)
                act = gsm.active_dict.pop(act_uuid, None)
                for asm in gsm.server_dict.values():
                    for epm in asm.endpoints.values():
                        ep_act = epm.active_dict.pop(act_uuid, None)
                        if act is None and ep_act is not None:
                            act = ep_act
                self.pruned_uuids.add(uuid_str)
                if act is None:
                    LOGGER.warning(
                        f"PruneDeadActions: uuid {uuid_str} not in any "
                        "active_dict; nothing to prune"
                    )
                    continue
                if HloStatus.finished not in act.action_status:
                    # guarded-status idiom (action.py:172), not a raw append
                    act.append_action_status(HloStatus.finished)
                if act.action_finished_timestamp is None:
                    act.action_finished_timestamp = now
                if HloStatus.finished not in gsm.nonactive_dict:
                    gsm.nonactive_dict[HloStatus.finished] = {}
                gsm.nonactive_dict[HloStatus.finished][act_uuid] = act
                if act.action_timestamp is not None:
                    orch.register_action_uuid(act_uuid, action_history_meta(orch, act))
                LOGGER.warning(
                    f"pruned dead-peer action {uuid_str} "
                    f"({act.action_server.server_name}/{act.action_name})"
                )
            return None

        raise AssertionError(f"unhandled reducer command: {cmd!r}")
