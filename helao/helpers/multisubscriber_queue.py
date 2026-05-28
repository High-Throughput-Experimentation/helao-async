"""Fan-out asyncio queue allowing multiple subscribers per producer.

Each subscriber receives its own ``asyncio.Queue`` so producers can ``put``
data once and have it delivered to every active subscriber. Adapted from
Kyle Smith's ``asyncio-multisubscriber-queue``.
"""

__all__ = ["MultisubscriberQueue"]


from asyncio import Queue
from typing import Any


# multisubscriber queue by Kyle Smith
# https://github.com/smithk86/asyncio-multisubscriber-queue
class MultisubscriberQueue:
    """Producer-side dispatcher that fans data out to many subscriber queues.

    Each call to ``subscribe`` (or to ``queue``) registers a fresh
    ``asyncio.Queue``. Every ``put``/``put_nowait`` writes the same item
    onto every registered queue, and ``close`` terminates all subscribers.
    """

    def __init__(self, **kwargs):
        """Initialise an empty subscriber list.

        Args:
            **kwargs: Accepted for forward compatibility; currently ignored.
        """
        super().__init__()
        self.subscribers = []

    def __len__(self) -> int:
        """Return the current subscriber count."""
        return len(self.subscribers)

    def __contains__(self, q) -> bool:
        """Return ``True`` when ``q`` is one of the registered subscribers."""
        return q in self.subscribers

    async def subscribe(self):
        """Async-iterate values delivered to a freshly registered queue.

        Yields:
            Each value put on the dedicated subscriber queue, until a
            ``StopAsyncIteration`` sentinel is received (sent by ``close``).
        """
        with self.queue_context() as q:
            while True:
                val = await q.get()
                if val is StopAsyncIteration:
                    break
                else:
                    yield val

    def queue(self) -> Queue:
        """Register and return a new subscriber ``asyncio.Queue``."""
        q = Queue()
        self.subscribers.append(q)
        return q

    def queue_context(self) -> "_QueueContext":
        """Return a context manager that auto-removes its subscriber queue."""
        return _QueueContext(self)

    def remove(self, q):
        """Remove a previously registered subscriber queue.

        Args:
            q: The queue to remove.

        Raises:
            KeyError: If ``q`` is not currently registered.
        """
        if q in self.subscribers:
            self.subscribers.remove(q)
        else:
            raise KeyError("subscriber queue does not exist")

    async def put(self, data: Any):
        """Await-put ``data`` on every subscriber queue."""
        for q in self.subscribers:
            await q.put(data)

    def put_nowait(self, data: Any):
        """Non-blocking put of ``data`` on every subscriber queue."""
        for q in self.subscribers:
            q.put_nowait(data)

    async def close(self):
        """Terminate every active ``subscribe`` iterator.

        Sends ``StopAsyncIteration`` as a sentinel on every subscriber queue.
        """
        await self.put(StopAsyncIteration)


class _QueueContext:
    """Context manager that registers a subscriber queue and removes it on exit.

    Attributes:
        parent: The owning ``MultisubscriberQueue``.
        queue: The subscriber queue created on ``__enter__``.
    """

    def __init__(self, parent):
        """Store the parent ``MultisubscriberQueue``.

        Args:
            parent: The owning ``MultisubscriberQueue``.
        """
        self.parent = parent
        self.queue = None

    def __enter__(self) -> Queue:
        """Register a fresh subscriber queue and return it."""
        self.queue = self.parent.queue()
        return self.queue

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Unregister the subscriber queue from the parent."""
        self.parent.remove(self.queue)
