"""The ``/ws_orch`` frame: a plain-dict snapshot of a running orchestrator.

Built read-only by :class:`helao.hexagon.app.orch_graph_feed.OrchGraphFeed`.
Plain data (str/int/float/bool/None/list/dict) so ``ws_utils.wire_dumps`` sends
it as an untagged ``[None, dict]`` frame with no special case.

Times are epoch seconds, or ``None`` until known. Item ``state`` is one of
``queued | active | done | error``; server ``status`` one of
``idle | busy | error | estop | unreachable``.
"""

import itertools
from collections import deque
from datetime import datetime
from typing import Optional

ERROR_STATUSES = frozenset({"errored", "aborted", "estopped"})
TERMINAL_OK = frozenset({"finished", "skipped", "split", "retired"})
EXP_DONE_WINDOW = 20
EXP_QUEUED_WINDOW = 50
ACT_QUEUED_WINDOW = 200


def _v(value) -> str:
    """Enum member or plain value -> its string value."""
    return str(getattr(value, "value", value))


def epoch(ts) -> Optional[float]:
    """Epoch seconds of a (naive, local) datetime, or None."""
    return ts.timestamp() if isinstance(ts, datetime) else None


def _names(statuses) -> set:
    return {_v(s) for s in (statuses or [])}


def _item_state(statuses) -> str:
    """done/error for a finished record; active while nothing terminal is set."""
    names = _names(statuses)
    if names & ERROR_STATUSES:
        return "error"
    if names & TERMINAL_OK:
        return "done"
    return "active"


def _seq_ended(seq, finished: bool) -> Optional[str]:
    """How a finished sequence ended: ``estopped``, ``error`` or ``finished``.

    ``None`` while it is still the active sequence."""
    if not finished:
        return None
    names = _names(getattr(seq, "sequence_status", None))
    if "estopped" in names:
        return "estopped"
    if names & ERROR_STATUSES:
        return "error"
    return "finished"


def _head(dq):
    """O(1) identity of a queue's head: the stored object (a zdeque's raw blob)."""
    return deque.__getitem__(dq, 0) if dq else None


def _queued(dq, window, build, cache, slot):
    """``build(item)`` rows of ``dq``'s first ``window`` items.

    A zdeque unpickles every item it yields, so with a ``cache`` dict the rows
    are rebuilt only when the length or the head's identity changes (an edit
    that keeps both, such as a middle removal paired with an append, shows on
    the next change).
    """
    key = (len(dq), _head(dq))
    hit = None if cache is None else cache.get(slot)
    if hit is not None and hit[0][0] == key[0] and hit[0][1] is key[1]:
        return hit[1]
    rows = [build(i, x) for i, x in enumerate(itertools.islice(dq, window))]
    if cache is not None:
        cache[slot] = (key, rows)
    return rows


def server_rows(orch, finish_errors: dict) -> list:
    """Every config ``group: action`` server, plus any other the orch knows."""
    gsm = orch.globalstatusmodel
    estopped = {key[0] for key, model in gsm.server_dict.items() if model.estop}
    active = {}
    for act in gsm.active_dict.values():
        active.setdefault(act.action_server.server_name, act.action_name)
    servers = orch.world_cfg.get("servers") or {}
    keys = [
        k
        for k, cfg in servers.items()
        if isinstance(cfg, dict) and cfg.get("group") == "action"
    ]
    extra = {key[0] for key in gsm.server_dict} - set(keys) - {orch.server_key}
    keys += sorted(k for k in extra if k not in servers)
    rows = []
    for key in keys:
        summary = orch.status_summary.get(key)
        if summary and summary[0] == "unreachable":
            status = "unreachable"
        elif key in estopped:
            status = "estop"
        elif key in active:
            status = "busy"
        elif finish_errors.get(key) in ERROR_STATUSES:
            status = "error"
        else:
            status = "idle"
        rows.append({"key": key, "status": status, "active_action": active.get(key)})
    return rows


def _of_seq(exp, seq_uuid) -> bool:
    """Whether ``exp`` belongs to ``seq`` (an experiment with no recorded parent does).

    The orchestrator activates the next sequence while the previous one's last
    experiment is still closing out, and files that experiment under the NEW
    sequence's ``dispatched_experiments``. Measured on goldenreflex: the second
    sequence's strip kept the first one's last experiment as a done row.
    """
    u = getattr(exp, "sequence_uuid", None)
    return u is None or seq_uuid is None or str(u) == seq_uuid


def experiment_rows(orch, cache=None) -> tuple:
    """Windowed experiments of the active sequence: ``(rows, n_done, n_queued)``.

    Queued experiments get a uuid at enqueue (queued actions at unpack), so a
    queued row carries one; ``qidx`` is its ABSOLUTE index in
    ``experiment_dq``. The deque unpickles each item on access, so only the
    queued window is read.
    """
    seq = orch.active_sequence or getattr(orch, "last_sequence", None)
    finished = orch.active_sequence is None and seq is not None
    seq_uuid = str(seq.sequence_uuid) if seq is not None else None
    done_all = [
        e
        for e in (getattr(seq, "dispatched_experiments", None) or [] if seq else [])
        if _of_seq(e, seq_uuid)
    ]
    done = done_all[-EXP_DONE_WINDOW:]
    rows = [
        {
            "uuid": str(e.experiment_uuid),
            "name": e.experiment_name,
            "state": "error" if _item_state(e.experiment_status) == "error" else "done",
            "t_start": epoch(e.experiment_timestamp),
            "t_end": epoch(e.experiment_finished_timestamp),
            "qidx": None,
        }
        for e in done
    ]
    exp = orch.active_experiment
    if (
        exp is not None
        and _of_seq(exp, seq_uuid)
        and str(exp.experiment_uuid) not in {r["uuid"] for r in rows}
    ):
        rows.append(
            {
                "uuid": str(exp.experiment_uuid),
                "name": exp.experiment_name,
                "state": "active",
                "t_start": epoch(exp.experiment_timestamp),
                "t_end": None,
                "qidx": None,
            }
        )
    if not finished:  # a finished sequence queues nothing
        rows += _queued(
            orch.experiment_dq,
            EXP_QUEUED_WINDOW,
            lambda idx, e: {
                "uuid": str(e.experiment_uuid) if e.experiment_uuid else None,
                "name": e.experiment_name,
                "state": "queued",
                "t_start": None,
                "t_end": None,
                "qidx": idx,
            },
            cache,
            "exp",
        )
    n_done = len(done_all) - len(done)
    n_queued = (
        max(0, len(orch.experiment_dq) - EXP_QUEUED_WINDOW) if not finished else 0
    )
    return rows, n_done, n_queued


def _queued_action(_idx, a):
    """``(uuid, row)`` of one queued action."""
    return a.action_uuid, {
        "uuid": str(a.action_uuid) if a.action_uuid else None,
        "name": a.action_name,
        "server": a.action_server.server_name,
        "state": "queued",
        "t_start": None,
        "t_end": None,
    }


def act_experiment(orch) -> tuple:
    """``(experiment, live)``: the experiment whose actions the ACT strip shows.

    The active one; with none (between two experiments, or idle after a queue)
    the last finished one, so the strip changes only when a NEW experiment
    starts. ``last_experiment`` is set before ``active_experiment`` clears; a
    fresh orchestrator falls back to the newest of the sequence's dispatched
    experiments.
    """
    exp = orch.active_experiment
    if exp is not None:
        return exp, True
    last = getattr(orch, "last_experiment", None)
    if last is None:
        seq = orch.active_sequence or getattr(orch, "last_sequence", None)
        done = getattr(seq, "dispatched_experiments", None) or []
        last = done[-1] if done else None
    return last, False


def action_rows(orch, first_seen: dict, cache=None) -> list:
    """Actions of :func:`act_experiment`: dispatched, then active-only, then queued.

    Looks the experiment's own uuids up per bucket instead of scanning
    ``nonactive_dict``, which holds every finished action since orch start.
    A finished experiment's actions are all done or error, and it has no queue.
    """
    exp, live = act_experiment(orch)
    if exp is None:
        return []
    gsm = orch.globalstatusmodel
    wanted = {a.action_uuid for a in exp.dispatched_actions or []}
    active = {}
    for u, a in gsm.active_dict.items():
        if u in wanted or a.experiment_uuid == exp.experiment_uuid:
            active[u] = a
    wanted |= set(active)
    # sort_status files a finished action under `finished` AND its sub-status, so
    # an error status must win whatever the dict order.
    finished = {}
    for u in wanted:
        for status, bucket in gsm.nonactive_dict.items():
            a = bucket.get(u)
            if a is None:
                continue
            name = _v(status)
            if not (u in finished and finished[u][0] in ERROR_STATUSES):
                finished[u] = (name, a)
    rows, seen = [], set()

    def add(u, model, state, t_end):
        if not live and state == "active":
            state = "done"  # nothing of a finished experiment is still running
        seen.add(u)
        uid = str(u)
        t_start = epoch(model.action_timestamp)
        rows.append(
            {
                "uuid": uid,
                "name": model.action_name,
                "server": model.action_server.server_name,
                "state": state,
                "t_start": t_start if t_start is not None else first_seen.get(uid),
                "t_end": t_end,
            }
        )

    for a in exp.dispatched_actions or []:
        u = a.action_uuid
        if u in seen:
            continue
        if u in active:
            add(u, active[u], "active", None)
        elif u in finished:
            status, model = finished[u]
            state = "error" if status in ERROR_STATUSES else "done"
            add(u, model, state, epoch(model.action_finished_timestamp))
        else:
            add(u, a, _item_state(a.action_status), epoch(a.action_finished_timestamp))
    for u, a in active.items():
        if u not in seen and a.experiment_uuid == exp.experiment_uuid:
            add(u, a, "active", None)
    if not live:
        return rows
    # The head action is popped before its start condition is waited on and is
    # held only here meanwhile (helao/hexagon/app/CLAUDE.md).
    parked = getattr(orch, "parked_head_action", None)
    queued = _queued(
        orch.action_dq,
        ACT_QUEUED_WINDOW,
        _queued_action,
        cache,
        "act",
    )
    if parked is not None:
        queued = [_queued_action(0, parked)] + queued
    rows += [row for u, row in queued if u not in seen]
    return rows


def build_snapshot(
    orch, *, seq_no, now, events, finish_errors, first_seen, queued_cache=None
) -> dict:
    """One ``/ws_orch`` frame. Reads only; never takes ``aiolock``."""
    gsm = orch.globalstatusmodel
    loop_state = _v(gsm.loop_state)
    seq = orch.active_sequence or getattr(orch, "last_sequence", None)
    experiments, n_done, n_queued = experiment_rows(orch, queued_cache)
    act_exp = act_experiment(orch)[0]
    orch_action = None
    for act in gsm.active_dict.values():
        if act.action_server.server_name == orch.server_key:
            orch_action = act.action_name
            break
    return {
        "seq_no": seq_no,
        "t": now,
        "orch_state": _v(gsm.orch_state),
        "loop_state": loop_state,
        "loop_intent": _v(gsm.loop_intent),
        "closing_out": loop_state == "stopped" and orch.active_experiment is not None,
        "n_sequences_queued": len(orch.sequence_dq),
        "seq": (
            None
            if seq is None
            else {
                "uuid": str(seq.sequence_uuid),
                "name": seq.sequence_name,
                "label": seq.sequence_label,
                "t_start": epoch(seq.sequence_timestamp),
                "finished": orch.active_sequence is None,
                "ended": _seq_ended(seq, orch.active_sequence is None),
            }
        ),
        "orch_action": orch_action,
        "servers": server_rows(orch, finish_errors),
        "experiments": experiments,
        "n_done": n_done,
        "n_queued": n_queued,
        "act_exp": str(act_exp.experiment_uuid) if act_exp is not None else None,
        "actions": action_rows(orch, first_seen, queued_cache),
        "events": list(events),
    }
