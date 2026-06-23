"""Real S3 :class:`~helao.framework.ports.cloud_sink.CloudSink` adapter.

Ports the cloud-egress half of the legacy ``SyncDriver``
(``helao/core/drivers/data/sync_driver.py``):

- ``upload_bytes`` / ``upload_file`` port ``to_s3`` (lines 1579-1634): serialize
  a dict to JSON (or upload a file as-is), optional gzip, blocking boto3 upload
  wrapped in ``asyncio.to_thread``, with a retry loop that sleeps 30s between
  attempts. When no S3 client is configured the method returns ``True`` without
  doing anything (legacy lines 1599-1600).
- ``register_api`` ports ``to_api`` (lines 1636-1654), which never actually
  POSTs -- it returns ``True``. We port that faithfully.
- ``load_aws_config`` is the pure config-merge slice of ``__init__``
  (lines 681-691): given a config dict, if ``AWS_CONFIG_PATH`` is present in the
  environment, read the named profile and merge its credentials into the config.
- ``dict2json`` is the byte-for-byte port of the module helper (lines 80-94).

The boto3 ``Session`` / ``client('s3')`` creation (the I/O part, legacy lines
695-707) happens in ``__init__``, guarded by the presence of credentials.
"""
from __future__ import annotations

import asyncio
import codecs
import gzip
import io
import json
import logging
import os
from configparser import ConfigParser
from pathlib import Path
from typing import Optional, Union

import boto3

LOGGER = logging.getLogger(__name__)


def dict2json(input_dict: dict) -> io.BytesIO:
    """Serialize a dict to a UTF-8 JSON byte stream rewound to position 0.

    Byte-for-byte port of legacy ``sync_driver.dict2json`` (lines 80-94).

    Args:
        input_dict: Dictionary to serialize.

    Returns:
        A ``BytesIO`` containing the JSON bytes, ready for upload.
    """
    bio = io.BytesIO()
    stream_writer = codecs.getwriter("utf-8")
    wrapper_file = stream_writer(bio)
    json.dump(input_dict, wrapper_file)
    bio.seek(0)
    return bio


def load_aws_config(config: dict) -> dict:
    """Merge AWS profile credentials from ``AWS_CONFIG_PATH`` into ``config``.

    Pure config-merge slice of legacy ``SyncDriver.__init__`` (lines 681-691).
    Returns a *new* dict (does not mutate the input). If ``AWS_CONFIG_PATH`` is
    not set in the environment, or the requested profile is absent, the config is
    returned unchanged (aside from being copied).

    Args:
        config: Config dict, optionally carrying ``aws_profile``.

    Returns:
        A copy of ``config`` with the profile's credentials merged in (plus
        ``aws_config_path`` / ``aws_profile`` keys) when available.
    """
    merged = dict(config)
    aws_config_path = os.environ.get("AWS_CONFIG_PATH")
    if aws_config_path is None:
        return merged
    cparser = ConfigParser()
    with open(aws_config_path) as f:
        cparser.read_file(f)
    aws_profile = merged.get("aws_profile", "default")
    if aws_profile in cparser:
        aws_config = dict(cparser[aws_profile])
        merged.update(aws_config)
        merged["aws_config_path"] = aws_config_path
        merged["aws_profile"] = aws_profile
    return merged


class S3CloudSink:
    """A :class:`CloudSink` backed by a real boto3 S3 client.

    Satisfies ``isinstance(obj, CloudSink)`` via the runtime-checkable Protocol.

    Args:
        config: AWS-config dict. When it carries ``aws_config_path``,
            ``aws_access_key_id``, ``aws_secret_access_key``, and ``region``, a
            boto3 session + S3 client are created (legacy lines 695-707).
            Otherwise the sink runs unconfigured and uploads no-op to ``True``.
        bucket: Destination bucket. Falls back to ``config['aws_bucket']``.
        region: Optional region override; falls back to ``config['region']``.
        client: Optional pre-built S3 client (used for testing / injection). When
            supplied it takes precedence over building one from credentials.
    """

    def __init__(
        self,
        config: dict,
        bucket: Optional[str] = None,
        region: Optional[str] = None,
        client=None,
    ) -> None:
        self.config_dict = dict(config)
        self.api_host = self.config_dict.get("api_host", None)
        self.bucket = bucket if bucket is not None else self.config_dict.get("aws_bucket")

        if client is not None:
            self.aws_session = None
            self.s3 = client
            return

        if "aws_config_path" in self.config_dict:
            os.environ["AWS_CONFIG_PATH"] = self.config_dict["aws_config_path"]
            self.aws_session = boto3.Session(
                aws_access_key_id=self.config_dict["aws_access_key_id"],
                aws_secret_access_key=self.config_dict["aws_secret_access_key"],
                region_name=region
                if region is not None
                else self.config_dict["region"],
            )
            self.s3 = self.aws_session.client("s3")
        else:
            self.aws_session = None
            self.s3 = None

    async def upload_bytes(
        self,
        data: bytes,
        key: str,
        content_type: str = "application/json",
        compress: bool = False,
    ) -> bool:
        """Upload ``data`` under ``key``; gzip when ``compress``.

        Ports the dict-branch of legacy ``to_s3`` (lines 1602-1631) for raw
        bytes: optional gzip (appending ``.gz`` to the key), blocking
        ``upload_fileobj`` via ``asyncio.to_thread``, 30s-wait retry loop.
        Returns ``True`` immediately if S3 is unconfigured.
        """
        try:
            if self.s3 is None:
                LOGGER.info("S3 is not configured. Skipping to S3 upload.")
                return True
            uploadee: io.BytesIO = io.BytesIO(data)
            if compress:
                if not key.endswith(".gz"):
                    key = f"{key}.gz"
                buffer = io.BytesIO()
                with gzip.GzipFile(fileobj=buffer, mode="wb") as f:
                    f.write(uploadee.read())
                buffer.seek(0)
                uploadee = buffer
            return await self._upload_with_retry(
                self.s3.upload_fileobj, uploadee, key
            )
        except Exception:
            LOGGER.error(f"Could not push {key}.", exc_info=True)
            return False

    async def upload_file(self, local_path: Path, key: str) -> bool:
        """Upload the file at ``local_path`` under ``key``.

        Ports the file-branch of legacy ``to_s3`` (lines 1614-1631): blocking
        ``upload_file`` via ``asyncio.to_thread`` with the 30s-wait retry loop.
        Returns ``True`` immediately if S3 is unconfigured.
        """
        try:
            if self.s3 is None:
                LOGGER.info("S3 is not configured. Skipping to S3 upload.")
                return True
            return await self._upload_with_retry(
                self.s3.upload_file, str(local_path), key
            )
        except Exception:
            LOGGER.error(f"Could not push {key}.", exc_info=True)
            return False

    async def _upload_with_retry(
        self, uploader, uploadee: Union[io.BytesIO, str], key: str, retries: int = 5
    ) -> bool:
        """Run ``uploader(uploadee, bucket, key)`` with the legacy retry loop.

        Mirrors legacy ``to_s3`` lines 1618-1631: ``retries + 1`` attempts, each
        wrapped in ``asyncio.to_thread``, sleeping 30s between failed attempts.
        """
        for i in range(retries + 1):
            if i > 0:
                LOGGER.info(f"S3 retry [{i}/{retries}]: {self.bucket}, {key}")
            try:
                await asyncio.to_thread(uploader, uploadee, self.bucket, key)
                return True
            except Exception:
                LOGGER.error(
                    f"Failed to upload {key} to S3, retrying in 30 seconds",
                    exc_info=True,
                )
                await asyncio.sleep(30)
        LOGGER.info(f"Did not upload {key} after {retries} tries.")
        return False

    def key_exists(self, key: str) -> bool:
        """Return ``True`` if an object already exists at ``key``.

        Legacy ``SyncDriver`` had no key-existence check; this is a reasonable
        ``head_object`` probe guarded by a configured client. Returns ``False``
        when S3 is unconfigured or the object is absent.
        """
        if self.s3 is None:
            return False
        try:
            self.s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    async def register_api(
        self, req_model: dict, meta_type: str, retries: int = 5
    ) -> bool:
        """Register ``req_model`` with the external API.

        Ports legacy ``to_api`` (lines 1636-1654) faithfully: it returns ``True``
        in all cases. The legacy implementation never performed the HTTP POST.

        # TODO(SP-later): legacy to_api never POSTs; real API registration deferred
        """
        if self.api_host is None:
            LOGGER.info("Modelyst API is not configured. Skipping to API push.")
            return True
        return True
