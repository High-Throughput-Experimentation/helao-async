"""Read-only feed behind ``/ws_orch``: orchestrator snapshots for the /group page.

Not a hook in the dispatch path. ``orch_dispatch.py``, ``orch_effects.py`` and
``ingestion.py`` are untouched, so none of the dispatch-loop traps in this
directory's CLAUDE.md is in play. Every 100 ms the feed reads state, never
takes ``aiolock`` and never mutates the orchestrator; a frame goes out only when
a cheap fingerprint changes, or every 2 s as a heartbeat so a client can tell a
quiet stream from a dead one. Events are derived by diffing ``active_dict`` and
``nonactive_dict`` uuid sets between ticks.
"""

import asyncio
import time
from typing import Optional

from helao.core.models.group_snapshot import (
    ERROR_STATUSES,
    _item_state,
    _names,
    _v,
    build_snapshot,
)
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

TICK_S = 0.1
HEARTBEAT_S = 2.0


def fingerprint(orch) -> tuple:
    """Everything a frame shows, cheaply. ``repr`` keeps dict driver statuses hashable."""
    gsm = orch.globalstatusmodel
    seq = orch.active_sequence or getattr(orch, "last_sequence", None)
    return (
        str(gsm.loop_state),
        str(gsm.loop_intent),
        str(gsm.orch_state),
        tuple(sorted((k, repr(v)) for k, v in orch.status_summary.items())),
        tuple(sorted((str(k), v) for k, v in gsm.counter_dispatched_actions.items())),
        frozenset(str(u) for u in gsm.active_dict),
        frozenset(
            (str(s), str(u)) for s, bucket in gsm.nonactive_dict.items() for u in bucket
        ),
        tuple(sorted(str(key[0]) for key, m in gsm.server_dict.items() if m.estop)),
        str(getattr(seq, "sequence_uuid", None)),
        len(getattr(seq, "dispatched_experiments", None) or ()),
        str(getattr(orch.active_experiment, "experiment_uuid", None)),
        len(orch.sequence_dq),
        len(orch.experiment_dq),
        len(orch.action_dq),
    )


class OrchGraphFeed:
    """Builds and publishes ``GroupSnapshot`` frames. One per ``OrchHost``."""

    def __init__(
        self, orch, queue, *, tick_s=TICK_S, heartbeat_s=HEARTBEAT_S, clock=time.time
    ):
        self.orch = orch
        self.queue = queue
        self.tick_s = tick_s
        self.heartbeat_s = heartbeat_s
        self.clock = clock
        #: The last frame built; the /ws_orch route sends it first on connect.
        self.latest: Optional[dict] = None
        self._seq_no = 0
        self._last_fp = None
        self._last_sent = float("-inf")
        self._primed = False
        self._prev_active: dict = {}
        self._prev_models: dict = {}
        self._prev_nonactive: set = set()
        self._finish_errors: dict = {}
        self._first_seen: dict = {}
        self._pending: list = []

    @staticmethod
    def _finish_status(names: set, first: str) -> str:
        errors = sorted(names & ERROR_STATUSES)
        return errors[0] if errors else first

    def diff_events(self, now: float) -> list:
        """dispatch/finish events since the previous tick."""
        gsm = self.orch.globalstatusmodel
        active_models = {str(u): a for u, a in gsm.active_dict.items()}
        active = {
            u: (a.action_server.server_name, a.action_name)
            for u, a in active_models.items()
        }
        # sort_status files a finished action under `finished` as well as its
        # sub-status, and estopped/aborted only there: the status comes from the
        # action's own statuses plus every bucket it sits in, error winning
        # whatever the dict order.
        nonactive: dict = {}
        for status, bucket in gsm.nonactive_dict.items():
            for u, a in bucket.items():
                server, name, names, first = nonactive.get(
                    str(u),
                    (a.action_server.server_name, a.action_name, set(), _v(status)),
                )
                names = names | {_v(status)} | _names(a.action_status)
                nonactive[str(u)] = (server, name, names, first)
        nonactive = {
            u: (server, name, self._finish_status(names, first))
            for u, (server, name, names, first) in nonactive.items()
        }
        events = []
        if self._primed:

            def ev(kind, uid, server, name, status):
                events.append(
                    {
                        "kind": kind,
                        "server": server,
                        "action_uuid": uid,
                        "action_name": name,
                        "status": status,
                        "t": now,
                    }
                )

            for uid, (server, name) in active.items():
                if uid not in self._prev_active:
                    self._first_seen.setdefault(uid, now)
                    ev("dispatch", uid, server, name, "active")
            for uid, (server, name, status) in nonactive.items():
                if uid in self._prev_nonactive:
                    continue
                if uid not in self._prev_active:
                    # started and finished between two ticks
                    ev("dispatch", uid, server, name, "active")
                ev("finish", uid, server, name, status)
            for uid, (server, name) in self._prev_active.items():
                if uid not in active and uid not in nonactive:
                    # left active_dict with no bucket entry (nonactive_dict was
                    # reset in the same tick): judge by the remembered model
                    state = _item_state(self._prev_models[uid].action_status)
                    ev(
                        "finish",
                        uid,
                        server,
                        name,
                        "errored" if state == "error" else "finished",
                    )
            for e in events:
                if e["kind"] == "finish":
                    self._finish_errors[e["server"]] = e["status"] in ERROR_STATUSES
        else:
            for uid in active:
                self._first_seen.setdefault(uid, now)
            self._primed = True
        self._prev_active = active
        self._prev_models = active_models
        self._prev_nonactive = set(nonactive)
        live = set(active) | set(nonactive)
        self._first_seen = {u: t for u, t in self._first_seen.items() if u in live}
        return events

    def step(self, now: float) -> Optional[dict]:
        """Return a new frame when something changed or a heartbeat is due."""
        self._pending.extend(self.diff_events(now))
        fp = fingerprint(self.orch)
        if (
            fp == self._last_fp
            and not self._pending
            and now - self._last_sent < self.heartbeat_s
        ):
            return None
        snap = build_snapshot(
            self.orch,
            seq_no=self._seq_no + 1,
            now=now,
            events=self._pending,
            finish_errors=self._finish_errors,
            first_seen=self._first_seen,
        )
        self._seq_no += 1
        self._pending = []
        self._last_fp = fp
        self._last_sent = now
        self.latest = snap
        return snap

    async def run(self) -> None:
        """Tick until cancelled. A failed frame is logged and skipped."""
        while True:
            try:
                snap = self.step(self.clock())
                if snap is not None:
                    self.queue.put_nowait(snap)
            except Exception:
                LOGGER.exception("orch graph feed: frame skipped")
            await asyncio.sleep(self.tick_s)
