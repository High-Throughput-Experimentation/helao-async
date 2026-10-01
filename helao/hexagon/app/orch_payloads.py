"""Read-only payload builders behind the orchestrator's queue and history routes.

Moved verbatim from ``helao/core/servers/orch_api.py`` by B7a. Each takes the
orchestrator (``OrchHost``) and reads its queues, histories,
``status_summary`` and ``step_thru_*`` flags at call time. They shape what
the Bokeh and Reflex operators parse, so there is one implementation, here.
"""

from typing import Optional


def _histories_payload(orch) -> dict:
    """Return action/experiment/sequence history as JSON-safe (uuid, dict) item lists."""
    return {
        "action": list(orch.action_history.items()),
        "experiment": list(orch.experiment_history.items()),
        "sequence": list(orch.sequence_history.items()),
    }


def _history_page_payload(orch, kind: str, limit: Optional[int], offset: int) -> dict:
    """Return one page of a history container, newest first.

    The reversal is done here rather than left to the caller because the page
    boundary depends on it: ``offset=0`` has to mean the *newest* entries, and a
    caller paging an oldest-first list would have to know the total to ask for
    the newest page -- which it would then race against, since the history grows
    under it.

    The three history containers are ``DequeDict``s, i.e. insertion-ordered
    dicts, so reversing their items is chronological. They are capped at 1000
    entries each, so materializing the reversed list costs nothing worth paging
    around.

    Args:
        orch: The orchestrator holding the history containers.
        kind: ``action``, ``experiment`` or ``sequence``.
        limit: Page size, or ``None`` for the whole history from ``offset``.
        offset: Number of entries to skip, counting back from the newest.

    Returns:
        dict: ``kind``, the full ``total``, the clamped ``offset``, and the
        page's ``(uuid, payload)`` ``items``. An unknown ``kind`` returns a
        ``total`` of 0 and no items rather than raising: the kind comes from a
        UI tab, and a typo there should not 500 the operator's poll.
    """
    history = {
        "action": getattr(orch, "action_history", None),
        "experiment": getattr(orch, "experiment_history", None),
        "sequence": getattr(orch, "sequence_history", None),
    }.get(kind)
    if history is None:
        return {"kind": kind, "total": 0, "offset": 0, "items": []}
    newest_first = list(history.items())[::-1]
    start = max(0, offset)
    stop = None if limit is None else start + max(0, limit)
    return {
        "kind": kind,
        "total": len(newest_first),
        "offset": start,
        "items": newest_first[start:stop],
    }


def _status_summary_payload(orch) -> dict:
    """Return {server: [server_status, driver_status]} from orch.status_summary."""
    return {k: list(v) for k, v in orch.status_summary.items()}


def _step_flags_payload(orch) -> dict:
    """Return the orchestrator's three step-through flags."""
    return {
        "actions": orch.step_thru_actions,
        "experiments": orch.step_thru_experiments,
        "sequences": orch.step_thru_sequences,
    }


def _set_step_flag(orch, kind: str, value: bool) -> dict:
    """Set one step-through flag by kind ('actions'|'experiments'|'sequences')."""
    attr = {
        "actions": "step_thru_actions",
        "experiments": "step_thru_experiments",
        "sequences": "step_thru_sequences",
    }[kind]
    setattr(orch, attr, bool(value))
    return {kind: getattr(orch, attr)}


def _queue_counts(orch) -> dict:
    """Return true queue lengths for the three deques."""
    return {
        "n_sequences": len(orch.sequence_dq),
        "n_experiments": len(orch.experiment_dq),
        "n_actions": len(orch.action_dq),
    }


def _queue_object_payload(orch, kind: str, idx: int) -> dict:
    """Return the full dict for the queued item of ``kind`` at ``idx``.

    Out-of-range indices or unknown kinds return ``{}`` (the queue may have
    mutated since the table was last polled — snapshot semantics).

    Mirrors ``RemoteBackend.get_queue_object``; keep the two in sync."""
    dq = {
        "sequence": getattr(orch, "sequence_dq", None),
        "experiment": getattr(orch, "experiment_dq", None),
        "action": getattr(orch, "action_dq", None),
    }.get(kind)
    if dq is None:
        return {}
    try:
        return dq[idx].as_dict()
    except (IndexError, KeyError, AttributeError):
        return {}
