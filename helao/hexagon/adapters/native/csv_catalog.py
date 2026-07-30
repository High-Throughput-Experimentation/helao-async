"""CsvTableCatalog: `TableCatalogPort` backed by a delimited text file on disk.

Replaces the module-scope `pd.read_csv("<station path>")` pattern in
deployment experiment/sequence libraries (see `ports/catalog.py` for why).

Two properties matter for parity:

- **Lazy.** Construction performs no I/O, so importing a library that wires
  one of these never touches the filesystem. The first `rows()`/`lookup_one()`
  call reads the file and caches the frame for the process lifetime, matching
  the legacy read-once-at-import behavior for a running station.
- **Non-fatal.** A missing or unparseable file logs once and degrades to an
  empty table, so every lookup returns None and the caller's documented
  fallback applies. Legacy crashed at import instead; that crash is precisely
  what made the libraries un-importable off-station.

`pandas` does the read so inferred cell dtypes stay identical to the legacy
`pd.read_csv` frame, and `lookup_one` extracts cells per column with
`.values[0]` -- the legacy expression verbatim -- so wire-visible metadata is
byte-for-byte what the station wrote before.
"""

import os
from collections.abc import Mapping, Sequence
from typing import Any, Optional

import pandas as pd

from helao.helpers import helao_logging as logging

LOGGER = logging.make_logger(__file__) if logging.LOGGER is None else logging.LOGGER

__all__ = ["CsvTableCatalog"]


class CsvTableCatalog:
    """A `TableCatalogPort` over a CSV (or other `pd.read_csv`-readable) file.

    Args:
        path: Location of the table. Not read until first use, and never
            required to exist.
        label: Short name used in log messages to identify which catalog is
            missing. Defaults to the file's basename.
        read_kwargs: Extra keyword arguments forwarded to `pd.read_csv`.
    """

    def __init__(
        self,
        path: "str | os.PathLike[str]",
        label: Optional[str] = None,
        **read_kwargs: Any,
    ):
        self.path = os.fspath(path)
        self.label = label or os.path.basename(self.path) or self.path
        self._read_kwargs = read_kwargs
        self._frame: Optional[pd.DataFrame] = None
        self._load_failed = False

    def prime(self) -> "CsvTableCatalog":
        """Read the table now and return self, for chaining at wiring time.

        Use this where the legacy code read at module import: the table then
        reflects the file as of import, not as of first lookup. That timing is
        wire-visible wherever another writer rewrites the table mid-run -- a
        lazy first read would silently pick up the newer table. Priming is
        still non-fatal, so an absent file leaves the library importable.
        """
        self._table()
        return self

    def reload(self) -> None:
        """Drop the cached frame so the next lookup re-reads the file.

        Lets an operator edit the table mid-run where a deployment wants that;
        no caller does by default.
        """
        self._frame = None
        self._load_failed = False

    def _table(self) -> pd.DataFrame:
        """Return the cached frame, reading it on first use.

        Read failures are logged once (subsequent lookups stay quiet) and
        yield an empty frame.
        """
        cached = self._frame
        if cached is not None:
            return cached
        try:
            frame = pd.read_csv(self.path, **self._read_kwargs)
        except Exception as exc:
            frame = None
            self._warn_once("unreadable at %s (%s)" % (self.path, exc))
        if not isinstance(frame, pd.DataFrame):
            # a chunked/iterator read_kwargs combination yields a reader, not a
            # frame; this port only serves whole tables
            if frame is not None:
                self._warn_once("read did not yield a table (check read_kwargs)")
            frame = pd.DataFrame()
        self._frame = frame
        return frame

    def _warn_once(self, detail: str) -> None:
        """Log a load failure the first time only; later lookups stay quiet."""
        if self._load_failed:
            return
        self._load_failed = True
        LOGGER.warning(
            "catalog '%s' %s; lookups will return no match and callers apply "
            "their fallback",
            self.label,
            detail,
        )

    def rows(self) -> Sequence[Mapping[str, Any]]:
        """Return every row as a column-keyed mapping (empty if unreadable)."""
        table = self._table()
        out: list[Mapping[str, Any]] = []
        for pos in range(len(table)):
            out.append(self._row_at(table, pos))
        return out

    def lookup_one(self, **keys: Any) -> Optional[Mapping[str, Any]]:
        """Return the single row matching every ``column == value`` pair.

        None when the table is unreadable, a key names a column the table does
        not have, or the match is not exactly one row -- the legacy
        `assert len(match) == 1` contract.
        """
        matched = self._matching(**keys)
        if matched is None or len(matched) != 1:
            return None
        return self._row_at(matched, 0)

    def lookup_first(self, **keys: Any) -> Optional[Mapping[str, Any]]:
        """Return the first row matching every ``column == value`` pair.

        Duplicate matches resolve to the first, reproducing legacy call sites
        that took `.values[0]` with no cardinality check.
        """
        matched = self._matching(**keys)
        if matched is None or matched.empty:
            return None
        return self._row_at(matched, 0)

    def _matching(self, **keys: Any) -> Optional[pd.DataFrame]:
        """Rows satisfying every ``column == value`` pair, or None if a key
        names a column the table does not have."""
        table = self._table()
        if table.empty:
            return table
        for column, value in keys.items():
            if column not in table.columns:
                LOGGER.warning(
                    "catalog '%s' has no column '%s' (columns: %s)",
                    self.label,
                    column,
                    list(table.columns),
                )
                return None
            table = table.loc[table[column] == value]
        return table

    @staticmethod
    def _row_at(table: pd.DataFrame, pos: int) -> Mapping[str, Any]:
        """Positional row as a column-keyed mapping, each cell read the way
        the legacy code did (`frame[col].values[pos]`) to preserve dtype."""
        return {col: table[col].values[pos] for col in table.columns}
