"""Pure global-status aggregation glue for the orchestrator FSM.

A thin, well-documented facade over :class:`GlobalStatusModel` (in
``helao.framework.models.server``). The orchestrator state machine (Wave 2)
queries and mutates aggregate action-server status through these free
functions rather than reaching into the model directly: it keeps the FSM's
call sites readable, gives the orchestration side one import surface for
status questions, and documents exactly which model operations the FSM relies
on.

Most helpers simply delegate to the equivalent `GlobalStatusModel` method; the
value they add is intent-revealing names and a stable seam for later
refactors. ``merge_server_status`` / ``newly_finished`` additionally normalise
the model's ``(uuid, status_name)`` tuples into a plain UUID list, which is
what the FSM actually consumes.

Purity: imports only from ``helao.framework.models`` and stdlib. No FastAPI /
httpx / asyncio / adapters / app coupling (enforced by the AST boundary test
``helao/framework/tests/test_boundaries.py``).
"""

__all__ = [
    "actions_idle",
    "server_free",
    "endpoint_free",
    "merge_server_status",
    "newly_finished",
]

from typing import List
from uuid import UUID

from helao.framework.models.machine import MachineModel
from helao.framework.models.server import ActionServerModel, GlobalStatusModel


def actions_idle(gsm: GlobalStatusModel) -> bool:
    """Return True if no action is active for the orchestrator owning `gsm`.

    Args:
        gsm: The orchestrator's aggregate status model.

    Returns:
        ``True`` when `gsm` has no active actions, otherwise ``False``.
    """
    return gsm.actions_idle()


def server_free(gsm: GlobalStatusModel, action_server: MachineModel) -> bool:
    """Return True if `action_server` has no active actions for this orchestrator.

    Args:
        gsm: The orchestrator's aggregate status model.
        action_server: The action server to query.

    Returns:
        ``True`` when no endpoint on `action_server` has an active action
        belonging to this orchestrator (including when the server is unknown).
    """
    return gsm.server_free(action_server)


def endpoint_free(
    gsm: GlobalStatusModel,
    action_server: MachineModel,
    endpoint_name: str,
) -> bool:
    """Return True if `endpoint_name` on `action_server` is free for this orch.

    Args:
        gsm: The orchestrator's aggregate status model.
        action_server: The action server hosting the endpoint.
        endpoint_name: The endpoint (action) name to query.

    Returns:
        ``True`` when the endpoint has no active action belonging to this
        orchestrator (including when the server or endpoint is unknown).
    """
    return gsm.endpoint_free(action_server, endpoint_name)


def newly_finished(
    gsm: GlobalStatusModel,
    actionservermodel: ActionServerModel,
) -> List[UUID]:
    """Merge a server status snapshot and return UUIDs that just finished.

    Wraps :meth:`GlobalStatusModel.update_global_with_acts` and projects its
    ``(uuid, status_name)`` tuples down to the action UUIDs that transitioned
    out of `active_dict` on this update — the form the orchestrator FSM
    consumes when it reacts to completions.

    Args:
        gsm: The orchestrator's aggregate status model (mutated in place).
        actionservermodel: Latest status snapshot from one action server.

    Returns:
        UUIDs of actions that newly transitioned to a finished state.
    """
    recent_nonactive = gsm.update_global_with_acts(actionservermodel)
    return [uuid for uuid, _status_name in recent_nonactive]


def merge_server_status(
    gsm: GlobalStatusModel,
    actionservermodel: ActionServerModel,
) -> List[UUID]:
    """Merge a server status snapshot into `gsm`; return newly-finished UUIDs.

    Alias of :func:`newly_finished` reading from the merge side: the orchestrator
    calls this when it receives a status push from an action server and wants
    both the side effect (the snapshot folded into `gsm`) and the list of
    actions that just completed.

    Args:
        gsm: The orchestrator's aggregate status model (mutated in place).
        actionservermodel: Latest status snapshot from one action server.

    Returns:
        UUIDs of actions that newly transitioned to a finished state.
    """
    return newly_finished(gsm, actionservermodel)
