"""The ``/ws_orch`` frame: a plain-dict snapshot of a running orchestrator.

Built read-only by :class:`helao.hexagon.app.orch_graph_feed.OrchGraphFeed`.
Plain data (str/int/float/bool/None/list/dict) so ``ws_utils.wire_dumps`` sends
it as an untagged ``[None, dict]`` frame with no special case.

Times are epoch seconds, or ``None`` until known. Item ``state`` is one of
``queued | active | done | error``; server ``status`` one of
``idle | busy | error | estop | unreachable``.
"""

import itertools
from datetime import datetime
from typing import Optional

ERROR_STATUSES = frozenset({"errored", "aborted", "estopped"})
TERMINAL_OK = frozenset({"finished", "skipped", "split", "retired"})
EXP_DONE_WINDOW = 20
EXP_QUEUED_WINDOW = 50


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
        elif finish_errors.get(key):
            status = "error"
        else:
            status = "idle"
        rows.append({"key": key, "status": status, "active_action": active.get(key)})
    return rows


def experiment_rows(orch) -> tuple:
    """Windowed experiments of the active sequence: ``(rows, n_done, n_queued)``.

    Queued experiments have no uuid until ``init_exp`` runs at activation, so a
    queued row carries ``qidx``, its ABSOLUTE index in ``experiment_dq``. The
    deque unpickles each item on access, so only the queued window is read.
    """
    seq = orch.active_sequence
    done_all = list(getattr(seq, "dispatched_experiments", None) or []) if seq else []
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
    if exp is not None and str(exp.experiment_uuid) not in {r["uuid"] for r in rows}:
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
    for idx, e in enumerate(itertools.islice(orch.experiment_dq, EXP_QUEUED_WINDOW)):
        rows.append(
            {
                "uuid": str(e.experiment_uuid) if e.experiment_uuid else None,
                "name": e.experiment_name,
                "state": "queued",
                "t_start": None,
                "t_end": None,
                "qidx": idx,
            }
        )
    n_done = len(done_all) - len(done)
    n_queued = max(0, len(orch.experiment_dq) - EXP_QUEUED_WINDOW)
    return rows, n_done, n_queued


def action_rows(orch, first_seen: dict) -> list:
    """Actions of the active experiment: dispatched, then active-only, then queued."""
    exp = orch.active_experiment
    if exp is None:
        return []
    gsm = orch.globalstatusmodel
    active = {str(u): a for u, a in gsm.active_dict.items()}
    finished = {}
    for status, bucket in gsm.nonactive_dict.items():
        for u, a in bucket.items():
            finished[str(u)] = (_v(status), a)
    rows, seen = [], set()

    def add(uid, model, state, t_end):
        seen.add(uid)
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
        uid = str(a.action_uuid)
        if uid in seen:
            continue
        if uid in active:
            add(uid, active[uid], "active", None)
        elif uid in finished:
            status, model = finished[uid]
            state = "error" if status in ERROR_STATUSES else "done"
            add(uid, model, state, epoch(model.action_finished_timestamp))
        else:
            add(
                uid, a, _item_state(a.action_status), epoch(a.action_finished_timestamp)
            )
    for uid, a in active.items():
        if uid not in seen and a.experiment_uuid == exp.experiment_uuid:
            add(uid, a, "active", None)
    for a in orch.action_dq:
        uid = str(a.action_uuid) if a.action_uuid else None
        rows.append(
            {
                "uuid": uid,
                "name": a.action_name,
                "server": a.action_server.server_name,
                "state": "queued",
                "t_start": None,
                "t_end": None,
            }
        )
    return rows


def build_snapshot(orch, *, seq_no, now, events, finish_errors, first_seen) -> dict:
    """One ``/ws_orch`` frame. Reads only; never takes ``aiolock``."""
    gsm = orch.globalstatusmodel
    loop_state = _v(gsm.loop_state)
    seq = orch.active_sequence
    experiments, n_done, n_queued = experiment_rows(orch)
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
            }
        ),
        "orch_action": orch_action,
        "servers": server_rows(orch, finish_errors),
        "experiments": experiments,
        "n_done": n_done,
        "n_queued": n_queued,
        "actions": action_rows(orch, first_seen),
        "events": list(events),
    }
