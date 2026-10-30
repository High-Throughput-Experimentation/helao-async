"""In-memory port fakes (spec §10.2): OPT-IN test doubles, never wired by
default composition.

Each fake logs a WARNING banner at construction so a "green on fakes" run is
visible in output; production composition (app/wiring.py) raises on unwired
ports and never defaults to these.
"""

import logging
import time
from datetime import datetime
from typing import Optional

LOGGER = logging.getLogger(__name__)


def _banner(name: str) -> None:
    LOGGER.warning("FAKE PORT IN USE: %s (test-only, never production)", name)


class FakeClock:
    def __init__(self, fixed: Optional[datetime] = None, offset_s: float = 0.0):
        _banner("FakeClock")
        self._fixed = fixed
        self._offset = offset_s

    def now(self) -> datetime:
        return self._fixed if self._fixed is not None else datetime.now()

    def now_ns(self) -> int:
        if self._fixed is not None:
            return int(self._fixed.timestamp() * 1e9)
        return time.time_ns()

    def offset(self) -> float:
        return self._offset


class FakeTableCatalog:
    """In-memory `TableCatalogPort`: rows supplied as dicts, no file at all.

    Lets a deployment library be exercised with a known table (and with an
    empty one, to cover the caller's fallback path) without a station CSV.
    """

    def __init__(self, rows: Optional[list[dict]] = None):
        _banner("FakeTableCatalog")
        self._rows: list[dict] = list(rows or [])

    def rows(self) -> list[dict]:
        return list(self._rows)

    def lookup_one(self, **keys) -> Optional[dict]:
        matched = self._matching(**keys)
        return dict(matched[0]) if len(matched) == 1 else None

    def lookup_first(self, **keys) -> Optional[dict]:
        matched = self._matching(**keys)
        return dict(matched[0]) if matched else None

    def _matching(self, **keys) -> list[dict]:
        return [
            row
            for row in self._rows
            if all(key in row and row[key] == val for key, val in keys.items())
        ]
