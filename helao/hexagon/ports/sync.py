"""Sync port (spec §4.3.4): the syncer surface callers actually use.

Bound at startup, not at ``build_wiring``: the syncer's ``__init__`` calls
``asyncio.create_task``, which needs a running loop. The orchestrator binds it
when ``use_sync`` is set; the SYNC server and the sim DB server bind it when
their ``app.driver`` exists. ``sync`` is in neither REQUIRED set, because
orchestrators with no SYNC server run without one.

Callers and the members they use:

- the orchestrator: ``to_s3`` (experiment and sequence meta, best effort);
- the SYNC / sim DB servers' routes: ``enqueue_yml``, ``release_quarantine``,
  ``list_pending``, ``finish_pending``, ``reset_sync``, ``write_off``,
  ``quarantined``, ``running_tasks``, ``n_queue``, and ``has_pending_work``
  (the hot-reload idle gate).

``reset_sync``, ``list_pending``, ``release_quarantine`` and ``quarantined`` are
synchronous on purpose: their routes are plain ``def`` and run in FastAPI's
threadpool, where a blocking unzip belongs.

Semantics carried by the native syncer (documented here as the contract):
hierarchical seq-RW/exp-mutex locks; children gate with
estopped-children-terminal rule; priority re-enqueue with rank floor -5;
file push; process reconcile+flush writing -prc.yml; patched meta JSON;
.lock cleanup; records sync in place (no move-to-SYNCED, no zipping) --
a config-defined post-finish hook chain (built-in s3_upload,
dispatch_analysis; see docs/superpowers/specs/2026-09-28-finish-hooks-design.md)
runs after the local gates and reconcile, tracked via the .prg `hooks`/
`synced` sidecar state; reset_sync reversal. S3: retries <=5 x 30 s via
asyncio.to_thread; unset S3 config => local-only success.
"""

from pathlib import Path
from typing import Protocol, Union, runtime_checkable

__all__ = ["SyncPort"]


@runtime_checkable
class SyncPort(Protocol):
    async def enqueue_yml(
        self, upath: Union[str, Path], rank: int = 0, rank_limit: int = -5
    ) -> None: ...

    def release_quarantine(self, yml_path: Union[Path, str]) -> bool: ...

    def list_pending(self, omit_manual_exps: bool = True) -> list: ...

    async def finish_pending(
        self, omit_manual_exps: bool = True, actions_first: bool = False
    ) -> list: ...

    def reset_sync(self, sync_path: str) -> bool: ...

    async def write_off(
        self, yml_path: Union[Path, str], reason: str, operator: str
    ) -> dict: ...

    def quarantined(self) -> list: ...

    def running_tasks(self) -> dict: ...

    def n_queue(self) -> int: ...

    def has_pending_work(self) -> bool: ...

    async def to_s3(
        self,
        msg: Union[dict, Path],
        target: str,
        retries: int = 5,
        compress: bool = False,
    ) -> bool: ...
