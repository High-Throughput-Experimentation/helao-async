"""HealthPort adapter (first consumer of the P1a ``HealthPort`` Protocol,
ports/auxiliary.py) — P2a.

``endpoints_available`` wraps the legacy HEAD-probe helper
(``helao.helpers.dispatcher.endpoints_available``) and converts its
``(all_available, [(url, [state]), ...])`` return into the port's declared
``[(url, ok), ...]`` shape (adapter-local conversion; the port is P1a-owned
and unchanged). ``ping_action_servers``/``status_summary`` need the live
``Orch``'s ``ServerMonitor`` and ``status_summary`` attribute, which do not
exist at ``build_wiring`` time — the adapter is constructed unbound and
``graft_hexagon_loop`` binds the orch at startup (fail loud before that;
same late-binding rationale as ``_LazyServerLogger``). ``status_summary``
values on the orch are ``(status_str, driver_status)`` tuples; the port
wants the driver status string ('unknown' gates dispatch), so the adapter
projects the second element."""

from helao.helpers.dispatcher import (
    endpoints_available as legacy_endpoints_available,
)

__all__ = ["LegacyHealthAdapter"]


class LegacyHealthAdapter:
    def __init__(self):
        self._orch = None

    def bind_orch(self, orch) -> None:
        self._orch = orch

    def _require_orch(self):
        if self._orch is None:
            raise RuntimeError(
                "LegacyHealthAdapter is not bound to a live Orch yet "
                "(graft_hexagon_loop binds it at startup)"
            )
        return self._orch

    async def endpoints_available(self, urls: list[str]) -> list[tuple[str, bool]]:
        _, unavail = await legacy_endpoints_available(list(urls))
        bad = {u for u, _ in unavail}
        return [(u, u not in bad) for u in urls]

    # ping_action_servers/status_summary are Protocol-SATISFIERS with a
    # provisional projection: NOTHING consumes them in P2a (the monitor uses
    # only endpoints_available; the driver-health gate reads
    # orch.status_summary directly at orch_effects.py:206). Revisit the
    # projections when they gain a real consumer.
    async def ping_action_servers(self) -> dict[str, str]:
        orch = self._require_orch()
        summary = await orch.server_monitor.ping_action_servers()
        return {k: status_str for k, (status_str, _driver) in summary.items()}

    def status_summary(self) -> dict[str, str]:
        orch = self._require_orch()
        return {k: driver for k, (_status, driver) in orch.status_summary.items()}
