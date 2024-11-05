__all__ = ["MultisubscriberQueue"]


from asyncio import Queue
from typing import Any


# multisubscriber queue by Kyle Smith
# https://github.com/smithk86/asyncio-multisubscriber-queue
class MultisubscriberQueue:
    """
    MultisubscriberQueue is a class that allows multiple subscribers to receive data from a single source asynchronously.

    Methods:
        __init__(**kwargs):
            Initializes the MultisubscriberQueue instance.
        
        __len__():
            Returns the number of subscribers.
        
        __contains__(q):
            Checks if a queue is in the list of subscribers.
        
        async subscribe():
            Subscribes to data using an async generator. Instead of working with the Queue directly, the client can subscribe to data and have it yielded directly.
        
        queue():
            Gets a new async Queue and adds it to the list of subscribers.
        
        queue_context():
            Gets a new queue context wrapper. The queue context wrapper allows the queue to be automatically removed from the subscriber pool when the context is exited.
        
        remove(q):
            Removes a queue from the pool of subscribers. Raises a KeyError if the queue does not exist.
        
        async put(data: Any):
            Puts new data on all subscriber queues.
                data: The data to be put on the queues.
        
        put_nowait(data: Any):
            Puts new data on all subscriber queues without waiting.
                data: The data to be put on the queues.
        
        async close():
            Forces clients using MultisubscriberQueue.subscribe() to end iteration.
    """
    def __init__(self, **kwargs):
        """
        Initializes a new instance of the class.

        Keyword Args:
            **kwargs: Arbitrary keyword arguments.
        """
        super().__init__()
        self.subscribers = []

    def __len__(self):
        """
        Return the number of subscribers.

        Returns:
            int: The number of subscribers in the queue.
        """
        return len(self.subscribers)

    def __contains__(self, q):
        """
        Check if a given queue is in the list of subscribers.

        Args:
            q: The queue to check for membership in the subscribers list.

        Returns:
            bool: True if the queue is in the subscribers list, False otherwise.
        """
        return q in self.subscribers

    async def subscribe(self):
        """
        Asynchronously subscribes to a queue and yields values from it.

        This coroutine function enters a queue context and continuously retrieves
        values from the queue. It yields each value until it encounters a 
        StopAsyncIteration, at which point it breaks the loop and stops the 
        subscription.

        Yields:
            Any: The next value from the queue.

        Raises:
            StopAsyncIteration: When the queue signals the end of iteration.
        """
        with self.queue_context() as q:
            while True:
                val = await q.get()
                if val is StopAsyncIteration:
                    break
                else:
                    yield val

    def queue(self):
        """
        Creates a new Queue instance, appends it to the subscribers list, and returns the Queue.

        Returns:
            Queue: A new Queue instance that has been added to the subscribers list.
        """
        q = Queue()
        self.subscribers.append(q)
        return q

    def queue_context(self):
        """
        Provides a context manager for the queue.

        Returns:
            _QueueContext: A context manager instance for the queue.
        """
        return _QueueContext(self)

    def remove(self, q):
        """
        Removes a subscriber queue from the list of subscribers.

        Args:
            q: The subscriber queue to be removed.

        Raises:
            KeyError: If the subscriber queue does not exist in the list of subscribers.
        """
        if q in self.subscribers:
            self.subscribers.remove(q)
        else:
            raise KeyError("subscriber queue does not exist")

    async def put(self, data: Any):
        """
        Asynchronously puts data into all subscriber queues.

        Args:
            data (Any): The data to be put into the subscriber queues.

        Returns:
            None
        """
        for q in self.subscribers:
            await q.put(data)

    def put_nowait(self, data: Any):
        """
        Put data into all subscriber queues without blocking.

        Args:
            data (Any): The data to be put into the subscriber queues.
        """
        for q in self.subscribers:
            q.put_nowait(data)

    async def close(self):
        """
        Asynchronously closes the queue by putting a StopAsyncIteration exception into it.

        This method should be called to signal that no more items will be added to the queue.
        """
        await self.put(StopAsyncIteration)


class _QueueContext:
    """
    _Context manager for handling queue operations within a parent context.

    Attributes:
        parent: The parent object that manages the queue.
        queue: The queue instance created within the context.

    Methods:
        __enter__:
            Initializes and returns a new queue instance from the parent.
        __exit__:
            Removes the queue instance from the parent upon exiting the context.

    Args:
        parent: The parent object that provides the queue management methods.
    """
    def __init__(self, parent):
        """
        Initializes the instance of the class.

        Args:
            parent: The parent object that this instance is associated with.
        """
        self.parent = parent
        self.queue = None

    def __enter__(self):
        """
        Enter the runtime context related to this object.

        This method is called when the 'with' statement is used. It initializes
        the queue attribute by calling the parent object's queue method and 
        returns the queue.

        Returns:
            queue.Queue: The queue instance created by the parent object.
        """
        self.queue = self.parent.queue()
        return self.queue

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Exit the runtime context related to this object.

        This method is called when the 'with' statement is used. It removes the 
        queue from the parent object.

        Parameters:
        exc_type (type): The exception type.
        exc_val (Exception): The exception instance.
        exc_tb (traceback): The traceback object.

        Returns:
        None
        """
        self.parent.remove(self.queue)
