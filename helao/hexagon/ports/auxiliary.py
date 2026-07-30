"""Auxiliary ports (spec §4.3.12)."""

from collections.abc import Callable
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

__all__ = [
    "HealthPort",
    "LibraryPort",
    "NotifyPort",
    "PlateInfoPort",
    "StatePersistencePort",
    "UuidFactoryPort",
]


@runtime_checkable
class StatePersistencePort(Protocol):
    """queues.pck export/import. Pickle shape per core-01 §2 including
    globalstatusmodel (runtime FSM state persists across restore — a parity
    behavior). Import archives the consumed pck (queues_imported_<ts>.pck)."""

    def export_queues(self, payload: dict, timestamp_pck: bool = False) -> Path: ...

    def import_queues(self) -> Optional[dict]: ...


@runtime_checkable
class PlateInfoPort(Protocol):
    """PLATE_API / HTEPlateAPI queries + the plate gate (verify_plates)."""

    async def get_platemap_plateid(self, plate_id: int) -> list: ...

    async def has_access(self, plate_id: int, usernames: list[str]) -> bool: ...


@runtime_checkable
class LibraryPort(Protocol):
    """Dynamic import of experiment/sequence/postprocessor libs +
    codehash/codepath provenance. Flat name-keyed registries with a LOAD-TIME
    COLLISION CHECK (silent shadowing becomes a loud preflight error,
    config-overridable for intentional shadowing)."""

    def experiment_lib(self) -> dict[str, Callable]: ...

    def sequence_lib(self) -> dict[str, Callable]: ...

    def provenance(self, func_name: str) -> tuple[str, str]:
        """Return (codehash, codepath) for a registered library function."""
        ...


@runtime_checkable
class HealthPort(Protocol):
    """HEAD-probe endpoints_available, ping_action_servers, heartbeat
    monitors (active_action_monitor default 10 s + ignore_heartbeats;
    driver-health status_summary gate)."""

    async def endpoints_available(self, urls: list[str]) -> list[tuple[str, bool]]: ...

    async def ping_action_servers(self) -> dict[str, str]: ...

    def status_summary(self) -> dict[str, str]:
        """server_key -> driver status string; 'unknown' gates dispatch."""
        ...


@runtime_checkable
class NotifyPort(Protocol):
    """Live buffer put, globstat/WS relay, LOGGER.alert."""

    def put_lbuf_nowait(self, payload: dict) -> None: ...

    async def publish_globstat(self, payload: dict) -> None: ...

    def alert(self, msg: str) -> None: ...


@runtime_checkable
class UuidFactoryPort(Protocol):
    """Identity minting seam so domain policies stay deterministic in tests."""

    def __call__(self) -> object: ...
