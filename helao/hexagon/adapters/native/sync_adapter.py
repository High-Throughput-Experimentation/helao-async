"""SyncPort adapter over the P2c native syncer (D4): thin delegation onto a
``NativeSyncer``/``SyncDriver`` instance from
``helao.hexagon.adapters.native.sync_driver``. All pipeline semantics (locks,
children gate, priority floor, process reconcile, .prg lifecycle) stay inside
the wrapped native driver — same shape as adapters/legacy/sync.py, which this
class replaces at the P2e DB cut-over. reset_sync/list_pending are sync in
the driver — bridged without behavior change. NOT constructed by
build_wiring in P2c (PortWiring.sync stays Optional-None; no REQUIRED entry)."""

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

    async def sync_yml(
        self,
        yml_path: Path,
        retries: int = 3,
        rank: int = 5,
        force_s3: bool = False,
        force_api: bool = False,
        compress: bool = False,
    ) -> dict:
        # native SyncDriver.sync_yml (verbatim legacy body) has early-exit
        # `return False` gate paths alongside its dict returns; the SyncPort
        # contract holds for callers that reach a real sync outcome.
        return await self._syncer.sync_yml(  # type: ignore[reportReturnType]
            yml_path,
            retries=retries,
            rank=rank,
            force_s3=force_s3,
            force_api=force_api,
            compress=compress,
        )

    async def finish_pending(self) -> list:
        return await self._syncer.finish_pending()

    async def reset_sync(self, sync_path: str) -> bool:
        return bool(self._syncer.reset_sync(sync_path))

    async def to_s3(
        self,
        msg: Union[dict, Path],
        target: str,
        retries: int = 5,
        compress: bool = False,
    ) -> bool:
        return await self._syncer.to_s3(msg, target, retries=retries, compress=compress)

    async def to_api(self, req_model: dict, meta_type: str, retries: int = 5) -> bool:
        return await self._syncer.to_api(req_model, meta_type, retries=retries)

    def list_pending(self, omit_manual_exps: bool = True) -> list:
        return self._syncer.list_pending(omit_manual_exps=omit_manual_exps)

    def n_queue(self) -> int:
        return int(self._syncer.task_queue.qsize())
