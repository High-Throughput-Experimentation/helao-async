"""Status ingestion fold + the normative §4.2.4 side-effect checklist.

Legacy behavior (orch_status_sync.StatusIngester.update_status, entirely
inside orch.aiolock — core-01 §4):
1. history registration on last_action_uuid match (unblocks the dispatch
   loop's history poll)                         -> RegisterHistoryEntry
2. register_obj_uuid/register_action_uuid on every enqueue/dispatch/finish
   path                                          -> NOT here; lives on the
   queue/dispatch paths (queue_policy + P1b runner); tested at those sites.
3. newly-nonactive (uuid, status_name) pairs     -> PushLiveBuffer
4. orch_state derivation (estopped-in-finished => estop; errored => error;
   empty active_dict => idle; else busy)         -> returned OrchStatus +
                                                    SetOrchStateError command
5. interrupt_q wake of the dispatch loop         -> WakeDispatchLoop
6. status-fold identity rule: finished actions are mirrored/removed only when
   statusmodel.orchestrator == gsm.orchestrator  -> inside the reused
   GlobalStatusModel._sort_status (D8); pinned by
   test_identity_rule_foreign_orchestrator_not_folded_into_own_dicts.

``fold_status`` mutates ``gsm`` in place (the model's own pure in-memory
fold, update_global_with_acts) and returns the derived orch_state plus the
ordered command tuple. It performs NO I/O; the P1b ingestion runner executes
the commands under the ingestion lock.

Drift fixed vs the task brief's sample code (verified against
helao/core/models/server.py -- GlobalStatusModel._sort_status /
update_global_with_acts):
``update_global_with_acts`` returns ``List[Tuple[UUID, str]]`` -- one
``(uuid, hlostatus.name)`` pair per bucket a uuid newly lands in (a single
status *name string*, not a nested collection of status names). The brief's
sample built ``PushLiveBuffer.items`` as
``Tuple[Tuple[UUID, Tuple[str, ...]], ...]`` and iterated
``tuple(str(s) for s in statuses)`` over the second element -- since that
element is a plain string in the real API, iterating it would silently
iterate its *characters* (e.g. ``"finished"`` -> ``('f','i',...)``) instead
of raising. Fixed by keeping ``PushLiveBuffer.items`` flat --
``Tuple[Tuple[UUID, str], ...]`` -- matching ``update_global_with_acts``
verbatim (byte-identical to the ``for act_uuid, act_status in
recent_nonactive`` loop in orch_status_sync.update_status, which calls
``put_lbuf`` once per pair, including a possible duplicate uuid across two
buckets, e.g. ``errored`` then ``finished``).
"""

from dataclasses import dataclass
from typing import Optional, Tuple
from uuid import UUID

from helao.hexagon.domain.models import (
    ActionServerModel,
    GlobalStatusModel,
    HloStatus,
    OrchStatus,
)

__all__ = [
    "PushLiveBuffer",
    "RegisterHistoryEntry",
    "SetOrchStateError",
    "TriggerEstopFromStatus",
    "WakeDispatchLoop",
    "fold_status",
]


@dataclass(frozen=True)
class RegisterHistoryEntry:
    """Checklist #1: rich history entry for the just-finished dispatched act."""

    action_uuid: UUID


@dataclass(frozen=True)
class PushLiveBuffer:
    """Checklist #3: newly-nonactive (uuid, status_name) pairs -> live buffer.

    ``items`` is flat -- one ``(uuid, status_name)`` pair per bucket a uuid
    newly transitioned into, matching
    ``GlobalStatusModel.update_global_with_acts`` verbatim (a uuid can appear
    more than once, e.g. once for ``errored`` and once for ``finished``).
    """

    items: Tuple[Tuple[UUID, str], ...]


@dataclass(frozen=True)
class WakeDispatchLoop:
    """Checklist #5: interrupt_q.put(globalstatusmodel)."""


@dataclass(frozen=True)
class TriggerEstopFromStatus:
    """Estopped uuid found in finished while loop started (core-01 T9 source).
    The runner feeds this back into the reducer as EstoppedUuidIngested."""

    reason: str


@dataclass(frozen=True)
class SetOrchStateError:
    """Errored uuids found while loop started (orch_state = error)."""


def fold_status(
    gsm: GlobalStatusModel,
    asm: ActionServerModel,
    *,
    loop_started: bool,
    last_dispatched_action_uuid: Optional[UUID],
) -> Tuple[OrchStatus, Tuple[object, ...]]:
    """Fold one pushed ActionServerModel into gsm; return (orch_state, cmds)."""
    commands: list = []

    # -- the model's own pure fold (D8): merge + _sort_status --------------
    newly_nonactive = gsm.update_global_with_acts(actionservermodel=asm)
    if newly_nonactive:
        commands.append(
            PushLiveBuffer(
                items=tuple(
                    (uuid, str(status_name)) for uuid, status_name in newly_nonactive
                )
            )
        )

    # -- checklist #1: history registration on last_action_uuid match ------
    reported_uuid = asm.last_action_uuid
    if (
        last_dispatched_action_uuid is not None
        and reported_uuid is not None
        and reported_uuid == last_dispatched_action_uuid
    ):
        commands.append(RegisterHistoryEntry(action_uuid=reported_uuid))

    # -- checklist #4 + estop/error reactions (core-01 §4 step 3) ----------
    estopped = gsm.find_hlostatus_in_finished(hlostatus=HloStatus.estopped)
    errored = gsm.find_hlostatus_in_finished(hlostatus=HloStatus.errored)
    if estopped and loop_started:
        commands.append(
            TriggerEstopFromStatus(
                reason=f"estopped uuids in finished: {sorted(map(str, estopped))}"
            )
        )
        orch_state = OrchStatus.estopped
    elif errored and loop_started:
        commands.append(SetOrchStateError())
        orch_state = OrchStatus.error
    elif not gsm.active_dict:
        orch_state = OrchStatus.idle
    else:
        orch_state = OrchStatus.busy

    # -- checklist #5: always wake the dispatch loop -----------------------
    commands.append(WakeDispatchLoop())
    return orch_state, tuple(commands)
