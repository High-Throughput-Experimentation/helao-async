"""Compressing :class:`collections.deque` subclass for memory-tight queues."""

import pickle
from collections import deque
from collections.abc import Iterator
from typing import Any

import pyzstd


class zdeque(deque):
    """:class:`collections.deque` that pickles + zstd-compresses every element.

    Reads decompress and unpickle on demand; writes pickle and compress before
    storing. Useful for queues holding large, repetitive payloads.
    """

    def __init__(self, iterable=(), maxlen=None):
        """Initialise like :class:`collections.deque`, compressing each item."""
        if maxlen is not None:
            super().__init__([], maxlen=maxlen)
        else:
            super().__init__()
        for x in iterable:
            self.append(x)

    def __getitem__(self, i) -> Any:
        """Return the decompressed and unpickled element at index ``i``."""
        x = super().__getitem__(i)
        return pickle.loads(pyzstd.decompress(x))

    def __iter__(self) -> Iterator[Any]:
        """Yield each element after decompressing and unpickling it."""
        for x in super().__iter__():
            yield pickle.loads(pyzstd.decompress(x))

    def popleft(self) -> Any:
        """Pop and return the leftmost element, decompressing and unpickling it."""
        x = super().popleft()
        return pickle.loads(pyzstd.decompress(x))

    def pop(self) -> Any:
        """Pop and return the rightmost element, decompressing and unpickling it."""
        x = super().pop()
        return pickle.loads(pyzstd.decompress(x))

    def insert(self, i, x):
        """Insert ``x`` at index ``i`` after pickling and compressing it."""
        super().insert(i, pyzstd.compress(pickle.dumps(x)))

    def append(self, x):
        """Append ``x`` to the right end after pickling and compressing it."""
        super().append(pyzstd.compress(pickle.dumps(x)))

    def appendleft(self, x):
        """Append ``x`` to the left end after pickling and compressing it."""
        super().appendleft(pyzstd.compress(pickle.dumps(x)))

    def index(self, x) -> int:
        """Return the index of ``x`` after pickling and compressing it.

        Raises:
            ValueError: If ``x`` is not present.
        """
        return super().index(pyzstd.compress(pickle.dumps(x)))
