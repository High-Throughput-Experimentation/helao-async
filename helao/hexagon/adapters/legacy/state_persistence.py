"""StatePersistencePort adapter: the queues.pck FILE contract (core-01 §2).

Reproduces orch_persist.QueuePersister's on-disk shape without holding an
orch back-reference (the port is payload-in/payload-out): STATES/queues.pck,
timestamped exports queues_<%y%m%d.%H%M%S>.pck, and the consumed-pck
archiving rule (a successfully imported queues.pck is renamed
queues_imported_<ts>.pck so hot-reload's unconditional --restore cannot
replay it). Building the payload from a live Orch stays the caller's job —
in P1b1 the ExportQueuesCmd effect delegates to orch.export_queues (the
wrapped legacy path); this adapter carries the contract for compositions
that have no legacy Orch (P2)."""

import os
import pickle
from datetime import datetime
from pathlib import Path
from typing import Optional

__all__ = ["QueuePckStore"]


class QueuePckStore:
    def __init__(self, root: str):
        self._states = Path(root) / "STATES"

    def export_queues(self, payload: dict, timestamp_pck: bool = False) -> Path:
        name = (
            f"queues_{datetime.now().strftime('%y%m%d.%H%M%S')}.pck"
            if timestamp_pck
            else "queues.pck"
        )
        path = self._states / name
        with open(path, "wb") as f:
            pickle.dump(payload, f)
        return path

    def import_queues(self) -> Optional[dict]:
        path = self._states / "queues.pck"
        if not path.exists():
            return None
        with open(path, "rb") as f:
            payload = pickle.load(f)
        archived = self._states / (
            f"queues_imported_{datetime.now().strftime('%y%m%d.%H%M%S')}.pck"
        )
        os.replace(path, archived)
        return payload
