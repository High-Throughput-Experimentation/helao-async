"""Asyncio synchronization helpers.

Ported verbatim from ``helao/core/drivers/data/sync_driver.py`` for SP6
(data sync). No behavior change -- the ``AsyncRWLock`` logic and docstring are
copied exactly from the legacy syncer.
"""
import asyncio
from contextlib import asynccontextmanager


class AsyncRWLock:
    """A minimal asyncio reader/writer lock.

    Any number of readers may hold the lock concurrently, but a writer has it
    exclusively. This is reader-preferring: a waiting writer does not block new
    readers from entering. That matters for the syncer's sequence locks -- a
    sequence (writer) can only finish once its descendants (readers) have, so a
    writer must never stall the very readers it is waiting on.
    """

    def __init__(self):
        self._cond = asyncio.Condition()
        self._readers = 0
        self._writer = False

    @asynccontextmanager
    async def read_locked(self):
        """Acquire shared (reader) access for the duration of the context."""
        async with self._cond:
            while self._writer:
                await self._cond.wait()
            self._readers += 1
        try:
            yield
        finally:
            async with self._cond:
                self._readers -= 1
                if self._readers == 0:
                    self._cond.notify_all()

    @asynccontextmanager
    async def write_locked(self):
        """Acquire exclusive (writer) access for the duration of the context."""
        async with self._cond:
            while self._writer or self._readers > 0:
                await self._cond.wait()
            self._writer = True
        try:
            yield
        finally:
            async with self._cond:
                self._writer = False
                self._cond.notify_all()
