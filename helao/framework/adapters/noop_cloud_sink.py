"""No-op :class:`~helao.framework.ports.cloud_sink.CloudSink` adapter.

Used for the ``use_s3 == False`` / S3-unconfigured path. Mirrors the legacy
``SyncDriver`` behavior where ``to_s3`` / ``to_api`` return ``True`` immediately
when no S3 client / API host is configured (``sync_driver.py`` lines 1599-1600,
1650-1652). Uploads always "succeed" (nothing is shipped), ``key_exists`` always
reports absence, and API registration is a no-op success.
"""
from __future__ import annotations

from pathlib import Path


class NoopCloudSink:
    """A :class:`CloudSink` that performs no I/O and always reports success.

    Satisfies ``isinstance(obj, CloudSink)`` via the runtime-checkable Protocol.
    """

    async def upload_bytes(
        self,
        data: bytes,
        key: str,
        content_type: str = "application/json",
        compress: bool = False,
    ) -> bool:
        """Pretend to upload ``data``; always returns ``True`` (no-op)."""
        return True

    async def upload_file(self, local_path: Path, key: str) -> bool:
        """Pretend to upload the file at ``local_path``; always returns ``True``."""
        return True

    def key_exists(self, key: str) -> bool:
        """Always returns ``False`` (no object store, so nothing exists)."""
        return False

    async def register_api(
        self, req_model: dict, meta_type: str, retries: int = 5
    ) -> bool:
        """No-op API registration; always returns ``True``."""
        return True
