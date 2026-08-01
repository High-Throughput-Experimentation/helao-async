"""Fixed-capacity buffers backing the Reflex UI stack's live plots.

:class:`RingBuffer` is a columnar float64 ring for plot data. Timestamps are
stored as epoch seconds, never as ``datetime`` objects, so the whole buffer is
one homogeneous numeric array and the plot facade owns axis formatting.

:class:`RowBuffer` is the deliberately dumb companion for mixed-type tabular
data (strings, UUIDs, labels) that has no place in a float64 ring.

Neither class performs IO or imports Reflex, so both are testable in isolation.
"""

__all__ = ["RingBuffer", "RowBuffer"]

import collections
from typing import Iterable, Optional, Sequence

import numpy as np


class RingBuffer:
    """Columnar float64 ring buffer with a fixed row capacity.

    Columns may be added after construction; existing rows are backfilled with
    ``nan``. A column known to the buffer but absent from an ``append`` call
    likewise receives ``nan`` for the appended rows, because HELAO action
    servers do not always publish every key in every message.

    Attributes:
        capacity: Maximum number of retained rows. Older rows are dropped.
    """

    def __init__(self, columns: Sequence[str], capacity: int = 1_000_000):
        """Allocate the ring.

        Args:
            columns: Initial column names.
            capacity: Maximum retained rows; must be positive.

        Raises:
            ValueError: If ``capacity`` is not positive.
        """
        if capacity <= 0:
            raise ValueError(f"capacity must be positive, got {capacity}")
        self.capacity = int(capacity)
        self._cols: dict[str, np.ndarray] = {}
        self._length = 0
        self._start = 0
        for name in columns:
            self._cols[name] = np.full(self.capacity, np.nan, dtype=np.float64)

    @property
    def columns(self) -> list:
        """Column names in insertion order."""
        return list(self._cols)

    @property
    def length(self) -> int:
        """Number of rows currently retained."""
        return self._length

    def ensure_columns(self, names: Iterable[str]) -> None:
        """Add any missing columns, backfilling existing rows with ``nan``.

        Args:
            names: Column names that must exist after this call.
        """
        for name in names:
            if name not in self._cols:
                self._cols[name] = np.full(self.capacity, np.nan, dtype=np.float64)

    def append(self, cols: dict) -> None:
        """Append rows, dropping the oldest once capacity is exceeded.

        Args:
            cols: Mapping of column name to an equal-length sequence of values.
                Unknown columns are created. Known columns absent from ``cols``
                receive ``nan``.

        Raises:
            ValueError: If the sequences are not all the same length, or a
                value is not coercible to float64.
        """
        if not cols:
            return
        lengths = {len(v) for v in cols.values()}
        if len(lengths) != 1:
            raise ValueError(f"ragged append: columns have differing lengths {
                    {k: len(v) for k, v in cols.items()}
                }")
        n = lengths.pop()
        if n == 0:
            return

        self.ensure_columns(cols)

        block = {}
        for name in self._cols:
            if name in cols:
                try:
                    arr = np.asarray(cols[name], dtype=np.float64)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"column '{name}' is not numeric: {exc}") from exc
            else:
                arr = np.full(n, np.nan, dtype=np.float64)
            block[name] = arr

        # An append larger than capacity can only keep its own tail.
        if n >= self.capacity:
            for name, arr in block.items():
                self._cols[name][:] = arr[-self.capacity :]
            self._length = self.capacity
            self._start = 0
            return

        write_at = (self._start + self._length) % self.capacity
        first = min(n, self.capacity - write_at)
        for name, arr in block.items():
            dest = self._cols[name]
            dest[write_at : write_at + first] = arr[:first]
            if first < n:
                dest[: n - first] = arr[first:]

        overflow = self._length + n - self.capacity
        if overflow > 0:
            self._start = (self._start + overflow) % self.capacity
            self._length = self.capacity
        else:
            self._length += n

    def snapshot(self, n: Optional[int] = None) -> dict:
        """Return the most recent rows as contiguous arrays, oldest first.

        Args:
            n: Number of trailing rows to return. ``None`` returns everything
                retained. Values larger than :attr:`length` return everything.

        Returns:
            ``{column_name: np.ndarray}``. Arrays are copies, safe to hand to
            the plot facade or a Reflex state var.
        """
        take = self._length if n is None else max(0, min(int(n), self._length))
        out = {}
        begin = (self._start + self._length - take) % self.capacity
        for name, dest in self._cols.items():
            if take == 0:
                out[name] = np.empty(0, dtype=np.float64)
            elif begin + take <= self.capacity:
                out[name] = dest[begin : begin + take].copy()
            else:
                head = self.capacity - begin
                out[name] = np.concatenate((dest[begin:], dest[: take - head]))
        return out

    def clear(self) -> None:
        """Drop all rows, keeping the column set."""
        self._length = 0
        self._start = 0
        for arr in self._cols.values():
            arr[:] = np.nan


class RowBuffer:
    """Bounded FIFO of dict rows for mixed-type tabular display.

    Used for table widgets whose columns include strings (server names, sample
    labels, UUIDs) and therefore cannot live in :class:`RingBuffer`.
    """

    def __init__(self, maxlen: int = 200):
        """Allocate the deque.

        Args:
            maxlen: Maximum retained rows.
        """
        self._rows = collections.deque(maxlen=maxlen)

    def append(self, row: dict) -> None:
        """Append one row, dropping the oldest when full."""
        self._rows.append(dict(row))

    def rows(self) -> list:
        """Return retained rows, oldest first."""
        return list(self._rows)

    def latest(self):
        """Return the most recent row, or ``None`` when empty."""
        return self._rows[-1] if self._rows else None

    def clear(self) -> None:
        """Drop all rows."""
        self._rows.clear()

    def __len__(self) -> int:
        """Number of retained rows."""
        return len(self._rows)
