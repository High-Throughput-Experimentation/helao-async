"""HealthPort adapter (first consumer of the P1a ``HealthPort`` Protocol,
ports/auxiliary.py) — P2a.

``endpoints_available`` wraps the legacy HEAD-probe helper
(``helao.helpers.dispatcher.endpoints_available``) and converts its
``(all_available, [(url, [state]), ...])`` return into the port's declared
``[(url, ok), ...]`` shape (adapter-local conversion; the port is P1a-owned
and unchanged)."""

from helao.helpers.dispatcher import (
    endpoints_available as legacy_endpoints_available,
)

__all__ = ["LegacyHealthAdapter"]


class LegacyHealthAdapter:
    async def endpoints_available(self, urls: list[str]) -> list[tuple[str, bool]]:
        _, unavail = await legacy_endpoints_available(list(urls))
        bad = {u for u, _ in unavail}
        return [(u, u not in bad) for u in urls]
