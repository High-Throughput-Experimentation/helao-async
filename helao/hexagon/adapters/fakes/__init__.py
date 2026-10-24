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

from helao.hexagon.domain.models import (
    Action,
    ErrorCodes,
)

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


class FakeTransport:
    """Records every dispatch; scripted responses/failures."""

    def __init__(
        self,
        respond_with: Optional[dict] = None,
        fail_with: Optional[ErrorCodes] = None,
    ):
        _banner("FakeTransport")
        self._respond_with = respond_with
        self._fail_with = fail_with
        self.dispatched: list[tuple[str, dict]] = []
        self.private_calls: list[tuple[str, str, dict]] = []
        self.probed: list[str] = []

    async def dispatch_action(
        self,
        action: Action,
        params: Optional[dict] = None,
        timeout: float = 60,
        retries: int = 5,
    ) -> tuple[Optional[dict], ErrorCodes]:
        method = f"{action.action_server.server_name}/{action.action_name}"
        payload = dict(params or {})
        payload["action"] = action.as_dict()
        self.dispatched.append((method, payload))
        if self._fail_with is not None:
            return None, self._fail_with
        return self._respond_with or action.as_dict(), ErrorCodes.none

    async def dispatch_private(
        self,
        server_key: str,
        host: str,
        port: int,
        private_action: str,
        params_dict: Optional[dict] = None,
        json_dict: Optional[dict] = None,
        timeout: float = 60,
        retries: int = 5,
    ) -> tuple[Optional[dict], ErrorCodes]:
        self.private_calls.append(
            (
                server_key,
                private_action,
                {**(params_dict or {}), **(json_dict or {})},
            )
        )
        if self._fail_with is not None:
            return None, self._fail_with
        return self._respond_with or {}, ErrorCodes.none

    async def check_endpoint(self, url: str, timeout: float = 3.0) -> bool:
        self.probed.append(url)
        return self._fail_with is None


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
