"""Push a MicroOrch's /group frames to Reflex backends (spec D1/D2).

Never in a run's way: each POST is short-timeout, errors are logged once per
target and swallowed, and a 409 (key held by another live runner) stops posting
to that target for good.
"""

import asyncio
import time
from typing import Optional

import httpx

from helao.core.models.group_snapshot import build_runner_snapshot
from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

TICK_S = 0.1
HEARTBEAT_S = 2.0
POST_TIMEOUT_S = 1.0


def fingerprint(m) -> tuple:
    """Everything a frame shows, cheaply."""
    return (
        tuple(sorted(str(u) for u in m.active_actions())),
        str(getattr(m.active_sequence, "sequence_uuid", None)),
        str(getattr(m.active_experiment, "experiment_uuid", None)),
        str(getattr(m.last_experiment, "experiment_uuid", None)),
        len(m.finished_experiments),
        len(m.queued_experiments),
        len(m.planned_actions),
        len(m.t_finish),
        tuple(sorted(m.server_estop.items())),
        tuple(sorted(m.finish_errors.items())),
        tuple(sorted(m.subscribed())),
    )


class RunnerGraphFeed:
    """Builds runner frames and POSTs them to every target URL."""

    def __init__(
        self,
        micro,
        urls,
        *,
        tick_s=TICK_S,
        heartbeat_s=HEARTBEAT_S,
        clock=time.time,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self.micro = micro
        self.urls = list(urls)
        self.tick_s = tick_s
        self.heartbeat_s = heartbeat_s
        self.clock = clock
        self.client = client or httpx.AsyncClient(timeout=POST_TIMEOUT_S)
        self.blocked: set = set()
        self._failing: set = set()
        self._seq_no = 0
        self._last_fp = None
        self._last_sent = float("-inf")

    def step(self, now: float) -> Optional[dict]:
        """A frame when something changed, events arrived, or a heartbeat is due."""
        events = self.micro.drain_events()
        fp = fingerprint(self.micro)
        if (
            fp == self._last_fp
            and not events
            and now - self._last_sent < self.heartbeat_s
        ):
            return None
        self._seq_no += 1
        self._last_fp, self._last_sent = fp, now
        return build_runner_snapshot(
            self.micro, seq_no=self._seq_no, now=now, events=events
        )

    def _path(self, url: str) -> str:
        return f"{url}/runners/{self.micro.server_key}"

    async def post(self, frame: dict) -> None:
        for url in self.urls:
            if url in self.blocked:
                continue
            try:
                r = await self.client.post(
                    f"{self._path(url)}/frame", json=frame, timeout=POST_TIMEOUT_S
                )
            except Exception as exc:
                if url not in self._failing:
                    self._failing.add(url)
                    LOGGER.warning(f"/group frame POST to {url} failed: {exc!r}")
                continue
            if r.status_code == 409:
                self.blocked.add(url)
                LOGGER.warning(
                    f"/group at {url} already shows a live runner named "
                    f"{self.micro.server_key!r}; not posting there"
                )
            elif r.status_code >= 400:
                if url not in self._failing:
                    self._failing.add(url)
                    LOGGER.warning(f"/group frame POST to {url}: HTTP {r.status_code}")
            else:
                self._failing.discard(url)

    async def run(self) -> None:
        """Tick until cancelled; a failed frame build is logged and skipped."""
        while True:
            try:
                frame = self.step(self.clock())
                if frame is not None:
                    await self.post(frame)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("runner graph feed: frame skipped")
            await asyncio.sleep(self.tick_s)

    async def close(self) -> None:
        """Deregister from every target (best effort), then close the client."""
        for url in self.urls:
            try:
                await self.client.delete(
                    self._path(url),
                    params={"instance": self.micro.instance},
                    timeout=POST_TIMEOUT_S,
                )
            except Exception:
                pass
        await self.client.aclose()
