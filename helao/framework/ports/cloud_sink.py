"""Cloud-sink port: async egress to object storage + API registration.

The data syncer ships finished-run artifacts off-box: it uploads JSON docs and
files to an S3-shaped object store and registers metadata with an external API.
Both legacy ``to_s3`` and ``to_api`` are async (boto3 is wrapped in
``asyncio.to_thread``), so this port mirrors that async shape. Expected failures
are reported as a ``bool`` return rather than raised.

Pure port (Protocols + typing only -- no I/O libraries). The real adapter lives
in ``adapters/s3_cloud_sink.py`` (with a ``NoopCloudSink`` for the unconfigured
case); the fake in ``adapters/fakes/cloud_sink.py``.
"""
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class CloudSink(Protocol):
    """Async egress: upload bytes/files to object storage and register metadata."""

    async def upload_bytes(
        self,
        data: bytes,
        key: str,
        content_type: str = "application/json",
        compress: bool = False,
    ) -> bool:
        """Upload ``data`` under ``key``; return ``True`` on success.

        ``compress`` optionally gzips the payload before upload.
        """
        ...

    async def upload_file(self, local_path: Path, key: str) -> bool:
        """Upload the file at ``local_path`` under ``key``; return ``True`` on success."""
        ...

    def key_exists(self, key: str) -> bool:
        """Return ``True`` if an object already exists at ``key``."""
        ...

    async def register_api(
        self, req_model: dict, meta_type: str, retries: int = 5
    ) -> bool:
        """Register ``req_model`` of ``meta_type`` with the external API; return ``True`` on success."""
        ...
