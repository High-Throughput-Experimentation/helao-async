"""Auxiliary ports (spec §4.3.12)."""

from typing import Optional, Protocol, runtime_checkable

__all__ = [
    "HealthPort",
    "StatePersistencePort",
]


@runtime_checkable
class StatePersistencePort(Protocol):
    """The queues.pck file contract: where it lives, how it is written, read,
    quarantined and archived. Pickle shape per core-01 §2 including
    globalstatusmodel (runtime FSM state persists across restore — a parity
    behavior). Building the payload, the schema check and applying it stay with
    ``QueuePersister``. All paths are ``os.path`` strings: ``/export_queues`` and
    ``/import_queues`` return them on the wire.

    - ``export_queues`` writes ``STATES/queues.pck`` (or the timestamped
      ``queues_<ts>.pck``, pruning that series) and returns its path.
    - ``load_queues`` returns ``(path, payload)``; ``payload`` is ``None`` when
      the file is missing, or unreadable (the file is first moved to
      ``queues_unreadable_<ts>.pck``).
    - ``archive_consumed`` renames a restored file to ``queues_imported_<ts>.pck``
      so a later unconditional ``--restore`` cannot replay it.
    """

    def export_queues(self, payload: dict, timestamp_pck: bool = False) -> str: ...

    def load_queues(
        self, pck_path: Optional[str] = None
    ) -> tuple[str, Optional[dict]]: ...

    def archive_consumed(self, path: str) -> Optional[str]: ...


@runtime_checkable
class HealthPort(Protocol):
    """HEAD-probe endpoints_available, heartbeat monitors (HexHealthMonitor:
    default 10 s + ignore_heartbeats)."""

    async def endpoints_available(self, urls: list[str]) -> list[tuple[str, bool]]: ...
