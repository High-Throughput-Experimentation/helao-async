"""Auxiliary ports (spec §4.3.12)."""

from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

__all__ = [
    "HealthPort",
    "StatePersistencePort",
]


@runtime_checkable
class StatePersistencePort(Protocol):
    """queues.pck export/import. Pickle shape per core-01 §2 including
    globalstatusmodel (runtime FSM state persists across restore — a parity
    behavior). Import archives the consumed pck (queues_imported_<ts>.pck)."""

    def export_queues(self, payload: dict, timestamp_pck: bool = False) -> Path: ...

    def import_queues(self) -> Optional[dict]: ...


@runtime_checkable
class HealthPort(Protocol):
    """HEAD-probe endpoints_available, ping_action_servers, heartbeat
    monitors (HexHealthMonitor: default 10 s + ignore_heartbeats;
    driver-health status_summary gate)."""

    async def endpoints_available(self, urls: list[str]) -> list[tuple[str, bool]]: ...

    async def ping_action_servers(self) -> dict[str, str]: ...

    def status_summary(self) -> dict[str, str]:
        """server_key -> driver status string; 'unknown' gates dispatch."""
        ...
