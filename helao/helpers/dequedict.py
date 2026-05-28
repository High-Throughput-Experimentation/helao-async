"""Bounded-length dict that evicts the oldest entry once capacity is reached."""


class DequeDict(dict):
    """``dict`` subclass that caps insertion-ordered length at ``maxlen``.

    Setting an item past capacity pops the oldest key (insertion order) so the
    dict behaves like a deque with key-based access. A ``maxlen`` of ``0``
    disables the eviction policy.
    """

    def __init__(self, *args, maxlen=0, **kwargs):
        """Initialize the dict and record the eviction threshold.

        Args:
            *args: Positional arguments forwarded to :class:`dict`.
            maxlen: Maximum number of entries to retain. ``0`` means unbounded.
            **kwargs: Keyword arguments forwarded to :class:`dict`.
        """
        self._maxlen = maxlen
        super().__init__(*args, **kwargs)

    def __setitem__(self, key, value):
        """Set ``key`` to ``value`` and evict the oldest entry if past ``maxlen``."""
        dict.__setitem__(self, key, value)
        if self._maxlen > 0:
            if len(self) > self._maxlen:
                self.pop(next(iter(self)))