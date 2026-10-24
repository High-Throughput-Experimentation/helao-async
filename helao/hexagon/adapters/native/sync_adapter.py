"""SyncPort adapter over the native syncer: thin delegation onto a
``NativeSyncer``/``SyncDriver`` instance from
``helao.hexagon.adapters.native.sync_driver``. All pipeline semantics (locks,
children gate, priority floor, process reconcile, .prg lifecycle) stay inside
the wrapped driver. ``reset_sync``, ``list_pending``, ``release_quarantine`` and
``quarantined`` are synchronous in the driver and stay synchronous here.

Not constructed by ``build_wiring``: the syncer's ``__init__`` needs a running
loop, so ``OrchHost``, the SYNC server and the sim DB server bind it from a
startup handler (``PortWiring.sync`` stays ``None`` until then, with no
REQUIRED entry)."""

from pathlib import Path
from typing import Union

from helao.hexagon.adapters.native.sync_driver import SyncDriver

__all__ = ["NativeSyncAdapter"]


class NativeSyncAdapter:
    def __init__(self, syncer: SyncDriver):
        self._syncer = syncer

    async def enqueue_yml(
        self, upath: Union[str, Path], rank: int = 0, rank_limit: int = -5
    ) -> None:
        await self._syncer.enqueue_yml(upath, rank=rank, rank_limit=rank_limit)

    def release_quarantine(self, yml_path: Union[Path, str]) -> bool:
        return self._syncer.release_quarantine(yml_path)

    def list_pending(self, omit_manual_exps: bool = True) -> list:
        return self._syncer.list_pending(omit_manual_exps=omit_manual_exps)

    async def finish_pending(
        self, omit_manual_exps: bool = True, actions_first: bool = False
    ) -> list:
        return await self._syncer.finish_pending(
            omit_manual_exps=omit_manual_exps, actions_first=actions_first
        )

    def reset_sync(self, sync_path: str) -> bool:
        return self._syncer.reset_sync(sync_path)

    async def write_off(
        self, yml_path: Union[Path, str], reason: str, operator: str
    ) -> dict:
        return await self._syncer.write_off(yml_path, reason, operator)

    def quarantined(self) -> list:
        return self._syncer.quarantined()

    def running_tasks(self) -> dict:
        return self._syncer.running_tasks

    def n_queue(self) -> int:
        return int(self._syncer.task_queue.qsize())

    def has_pending_work(self) -> bool:
        return self._syncer.has_pending_work()

    async def to_s3(
        self,
        msg: Union[dict, Path],
        target: str,
        retries: int = 5,
        compress: bool = False,
    ) -> bool:
        return await self._syncer.to_s3(msg, target, retries=retries, compress=compress)
