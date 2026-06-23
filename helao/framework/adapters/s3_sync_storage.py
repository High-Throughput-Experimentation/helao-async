"""S3SyncStorage stub: inherits FsSyncStorage, raises on upload methods.

Real boto3 implementation is deferred to a follow-on sub-project.
Import paths are stable: S3SyncStorage will keep this module path when
the real implementation replaces the stubs.
"""
from pathlib import Path

from helao.framework.adapters.fs_sync_storage import FsSyncStorage


class S3SyncStorage(FsSyncStorage):
    """FsSyncStorage + NotImplementedError stubs for cloud upload."""

    def upload_file(self, local_path: Path, s3_key: str) -> bool:
        raise NotImplementedError("S3 adapter deferred to follow-on SP")

    def upload_bytes(
        self, data: bytes, s3_key: str, content_type: str = "application/json"
    ) -> bool:
        raise NotImplementedError("S3 adapter deferred to follow-on SP")

    def key_exists(self, s3_key: str) -> bool:
        raise NotImplementedError("S3 adapter deferred to follow-on SP")
