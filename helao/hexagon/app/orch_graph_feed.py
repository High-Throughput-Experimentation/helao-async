"""Read-only feed behind ``/ws_orch``: orchestrator snapshots for the /group page.

Not a hook in the dispatch path. ``orch_dispatch.py``, ``orch_effects.py`` and
``ingestion.py`` are untouched, so none of the dispatch-loop traps in this
directory's CLAUDE.md is in play. Every 100 ms the feed reads state, never
takes ``aiolock`` and never mutates the orchestrator; a frame goes out only when
a cheap fingerprint changes, or every 2 s as a heartbeat so a client can tell a
quiet stream from a dead one. Events are derived by diffing ``active_dict``
between ticks and, for ``nonactive_dict`` (which only ever grows), against a
bounded set of uuids already reported, reading a bucket only when its length
changed: an unchanged tick does not grow with the finished actions.
"""

import asyncio
import time
from collections import OrderedDict
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
SEEN_CAP = 100_000
#: Log a persistently failing frame build once at first, then every Nth tick.
FAIL_LOG_EVERY = 600


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
        tuple((str(s), len(b)) for s, b in gsm.nonactive_dict.items()),
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
        #: Finished-action uuids already reported, oldest first, capped.
        self._seen_finished: OrderedDict = OrderedDict()
        self._bucket_lens: dict = {}
        self._prev_loop: Optional[str] = None
        #: server -> status of its latest finish; an entry is an error status
        #: until a later clean finish or the loop leaves ``estopped``.
        self._finish_errors: dict = {}
        self._first_seen: dict = {}
        self._pending: list = []
        self._queued_cache: dict = {}
        self._fail_n = 0

    @staticmethod
    def _finish_status(names: set, first: str) -> str:
        errors = sorted(names & ERROR_STATUSES)
        return errors[0] if errors else first

    def _new_finishes(self, gsm) -> dict:
        """``{uuid: (server, name, status)}`` of finishes not reported before.

        sort_status files a finished action under ``finished`` as well as its
        sub-status, and estopped/aborted only there: the status comes from the
        action's own statuses plus every bucket it sits in, error winning
        whatever the dict order. A bucket is read only when its length changed
        since the last tick, and only the uuids not yet remembered are kept,
        so none is ever re-emitted.
        """
        buckets = list(gsm.nonactive_dict.items())
        lens = {s: len(b) for s, b in buckets}
        changed = [b for s, b in buckets if lens[s] != self._bucket_lens.get(s)]
        self._bucket_lens = lens
        new: dict = {}  # insertion order = bucket order, so the cap evicts oldest
        for bucket in changed:
            new.update(dict.fromkeys(u for u in bucket if u not in self._seen_finished))
        out = {}
        for u in new:
            names, hit = set(), None
            for status, bucket in buckets:
                a = bucket.get(u)
                if a is None:
                    continue
                hit = hit or (a, _v(status))
                names |= {_v(status)} | _names(a.action_status)
            if hit is None:
                continue
            a, first = hit
            out[u] = (
                a.action_server.server_name,
                a.action_name,
                self._finish_status(names, first),
            )
        return out

    def _remember(self, uuids) -> None:
        for u in uuids:
            self._seen_finished[u] = None
        while len(self._seen_finished) > SEEN_CAP:
            self._seen_finished.popitem(last=False)

    def diff_events(self, now: float) -> list:
        """dispatch/finish events since the previous tick."""
        gsm = self.orch.globalstatusmodel
        active_models = dict(gsm.active_dict.items())
        active = {
            u: (a.action_server.server_name, a.action_name)
            for u, a in active_models.items()
        }
        loop = _v(gsm.loop_state)
        if self._prev_loop == "estopped" and loop != "estopped":
            # Clear E-stop: servers stop reading as errored for the estop.
            self._finish_errors = {
                k: v for k, v in self._finish_errors.items() if v != "estopped"
            }
        self._prev_loop = loop
        new = self._new_finishes(gsm)
        events = []
        if self._primed:

            def ev(kind, u, server, name, status):
                events.append(
                    {
                        "kind": kind,
                        "server": server,
                        "action_uuid": str(u),
                        "action_name": name,
                        "status": status,
                        "t": now,
                    }
                )

            for u, (server, name) in active.items():
                if u not in self._prev_active:
                    self._first_seen.setdefault(str(u), now)
                    ev("dispatch", u, server, name, "active")
            for u, (server, name, status) in new.items():
                if u not in self._prev_active:
                    # started and finished between two ticks
                    ev("dispatch", u, server, name, "active")
                ev("finish", u, server, name, status)
            vanished = {}
            for u, (server, name) in self._prev_active.items():
                if u not in active and u not in new and u not in self._seen_finished:
                    # left active_dict with no bucket entry (nonactive_dict was
                    # reset in the same tick): judge by the remembered model
                    state = _item_state(self._prev_models[u].action_status)
                    status = "errored" if state == "error" else "finished"
                    vanished[u] = None
                    ev("finish", u, server, name, status)
            self._remember(vanished)
            per_server: dict = {}
            for e in events:
                if e["kind"] != "finish":
                    continue
                old = per_server.get(e["server"])
                if old not in ERROR_STATUSES:  # an error wins within a tick
                    per_server[e["server"]] = e["status"]
            self._finish_errors.update(per_server)
        else:
            for u in active:
                self._first_seen.setdefault(str(u), now)
            self._primed = True
        self._remember(new)
        self._prev_active = active
        self._prev_models = active_models
        live = {str(u) for u in active} | {str(u) for u in new}
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
            queued_cache=self._queued_cache,
        )
        self._seq_no += 1
        self._pending = []
        self._last_fp = fp
        self._last_sent = now
        self.latest = snap
        return snap

    def _report_failure(self) -> None:
        """First failure with its traceback, then one line per FAIL_LOG_EVERY."""
        if self._fail_n % FAIL_LOG_EVERY == 0:
            if self._fail_n == 0:
                LOGGER.exception("orch graph feed: frame skipped")
            else:
                LOGGER.error(
                    f"orch graph feed: still failing ({self._fail_n} ticks skipped)"
                )
        self._fail_n += 1

    async def run(self) -> None:
        """Tick until cancelled. A failed frame is logged and skipped."""
        while True:
            try:
                snap = self.step(self.clock())
                if snap is not None:
                    self.queue.put_nowait(snap)
                if self._fail_n:
                    LOGGER.info(
                        f"orch graph feed: recovered after {self._fail_n} skipped ticks"
                    )
                    self._fail_n = 0
            except Exception:
                self._report_failure()
            await asyncio.sleep(self.tick_s)
