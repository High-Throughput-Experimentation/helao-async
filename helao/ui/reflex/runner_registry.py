"""Runners that push /group frames to this Reflex process (spec: Page side).

A runner's first ``POST /runners/{key}/frame`` registers it; ``DELETE`` marks it
ended. :class:`PushIngest` has the reading surface /group uses on ``WsIngest``
(``raw``, ``n_batches``, ``status``), so the page's frame helpers take either.
"""

import asyncio
import collections
import threading
import time
from typing import Optional

from fastapi import APIRouter, Request, Response

from helao.core.rpc import RPCClient
from helao.ui.reflex.ingest import IngestStatus

STALE_S = 5.0
EXPIRE_S = 600.0
RPC_TIMEOUT_S = 2.0


class PushIngest:
    """One runner's frames, newest last."""

    def __init__(self, instance: str):
        self.instance = instance
        self.raw: collections.deque = collections.deque(maxlen=200)
        self.n_batches = 0
        self.status = IngestStatus()
        self.ended = False
        self.last_frame_at = 0.0
        self._rpc: Optional[RPCClient] = None

    def put(self, frame: dict, now: float) -> None:
        self.raw.append([frame])
        self.n_batches += 1
        self.status.message_count += 1
        self.status.last_epoch = now
        self.status.state = "live"
        self.last_frame_at = now
        self.ended = False

    def end(self) -> None:
        """Deregistered: read as lost at once."""
        self.ended = True
        self.status.last_epoch = 0.0
        self.status.state = "ended"

    def lost(self, now: float) -> bool:
        return self.ended or now - self.status.last_epoch > STALE_S

    def rpc(self, host: str, port: int) -> RPCClient:
        if self._rpc is None:
            self._rpc = RPCClient(
                endpoint=f"tcp://{host}:{port}", default_timeout=RPC_TIMEOUT_S
            )
        return self._rpc

    async def aclose(self) -> None:
        if self._rpc is not None:
            await self._rpc.close()
            self._rpc = None


class RunnerRegistry:
    """``key -> PushIngest``; safe to read from the tick and write from routes."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self._lock = threading.Lock()
        self._entries: dict = {}
        self._reserved: set = set()

    def reserve(self, keys) -> None:
        """Keys a runner may not take (every server key of the page's config)."""
        self._reserved = set(keys)

    def post(self, key: str, frame: dict) -> int:
        instance = frame.get("instance") if isinstance(frame, dict) else None
        if not instance:
            return 400
        if key in self._reserved:
            return 409
        now = self.clock()
        replaced = None
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.instance != instance:
                if not entry.lost(now):
                    return 409
                replaced, entry = entry, None
            if entry is None:
                entry = PushIngest(instance)
                self._entries[key] = entry
            entry.put(frame, now)
        if replaced is not None:
            try:
                asyncio.get_running_loop().create_task(replaced.aclose())
            except RuntimeError:  # no loop (direct sync call): nothing to close on
                pass
        return 200

    def delete(self, key: str, instance: str) -> int:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.instance != instance:
                return 404
            entry.end()
        return 200

    def get(self, key: str) -> Optional[PushIngest]:
        with self._lock:
            return self._entries.get(key)

    def keys(self) -> list:
        with self._lock:
            return list(self._entries)

    def sweep(self, now: float) -> list:
        """Remove entries silent for ``EXPIRE_S``; return them for closing."""
        with self._lock:
            gone = [
                k for k, e in self._entries.items() if now - e.last_frame_at > EXPIRE_S
            ]
            return [self._entries.pop(k) for k in gone]


def make_runner_router(registry: RunnerRegistry) -> APIRouter:
    router = APIRouter()

    @router.post("/runners/{key}/frame")
    async def post_frame(key: str, request: Request) -> Response:
        try:
            frame = await request.json()
        except Exception:
            return Response(status_code=400)
        return Response(status_code=registry.post(key, frame))

    @router.delete("/runners/{key}")
    async def delete_runner(key: str, instance: str) -> Response:
        return Response(status_code=registry.delete(key, instance))

    @router.api_route("/runners_busy", methods=["GET", "POST"])
    async def runners_busy() -> dict:
        """Hot-reload gate (spec D4): restarting this server kills its runners."""
        from helao.ui.reflex import runner_procs  # lazy: runner_procs imports group

        return {"busy": runner_procs.busy()}

    return router


REGISTRY = RunnerRegistry()
