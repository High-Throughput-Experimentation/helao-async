"""Sync port (spec §4.3.4): HelaoSyncer/SyncDriver surface + S3 face.

Semantics carried by the P1b adapter (documented here as the contract):
hierarchical seq-RW/exp-mutex locks; children gate with
estopped-children-terminal rule; priority re-enqueue with rank floor -5;
file push; process reconcile+flush writing -prc.yml; patched meta JSON;
.lock cleanup; move-to-SYNCED; empty-dir pruning; destructive sequence zip;
optional auto-analysis dispatch; .prg sidecar lifecycle; reset_sync reversal.
S3: retries <=5 x 30 s via asyncio.to_thread; unset S3 config => local-only
success. The Sim DB server (P0) implements S3FacePort with a recording sink.
"""

from pathlib import Path
from typing import Optional, Protocol, Union, runtime_checkable

__all__ = ["S3FacePort", "SyncPort"]


@runtime_checkable
class S3FacePort(Protocol):
    async def upload(
        self,
        key: str,
        body: Union[dict, bytes, Path],
        content_type: str = "application/json",
        compress: bool = False,
    ) -> bool: ...


@runtime_checkable
class SyncPort(Protocol):
    async def enqueue_yml(
        self, upath: Union[str, Path], rank: int = 0, rank_limit: int = -5
    ) -> None: ...

    async def sync_yml(
        self,
        yml_path: Path,
        retries: int = 3,
        rank: int = 5,
        force_s3: bool = False,
        force_api: bool = False,
        compress: bool = False,
    ) -> dict: ...

    async def finish_pending(self) -> list: ...

    async def reset_sync(self, sync_path: str) -> bool: ...

    async def to_s3(
        self,
        msg: Union[dict, Path],
        target: str,
        retries: int = 5,
        compress: bool = False,
    ) -> bool: ...

    async def to_api(self, req_model: dict, meta_type: str, retries: int = 5) -> bool:
        """STUB by decision (spec §1.3): returns True unconditionally."""
        ...

    def list_pending(self, omit_manual_exps: bool = True) -> list: ...

    def n_queue(self) -> int: ...
