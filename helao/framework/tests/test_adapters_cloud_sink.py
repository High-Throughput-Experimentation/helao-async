"""Tests for the cloud-sink adapters (SP6 W3-B).

Covers:
- :class:`NoopCloudSink` truthy uploads, absent keys, Protocol conformance.
- :class:`S3CloudSink` with an injected fake boto3 client: payload/gzip/key/
  content-type assertions, file uploads, the 30s retry loop (with
  ``asyncio.sleep`` monkeypatched away), ``register_api`` no-op, the unconfigured
  no-op path, and Protocol conformance.
- The pure helpers ``load_aws_config`` and ``dict2json``.

No real network / S3 call is made.
"""
from __future__ import annotations

import asyncio
import gzip
import io
import json
from pathlib import Path

import pytest

from helao.framework.adapters.noop_cloud_sink import NoopCloudSink
from helao.framework.adapters.s3_cloud_sink import (
    S3CloudSink,
    dict2json,
    load_aws_config,
)
from helao.framework.ports.cloud_sink import CloudSink


# --------------------------------------------------------------------------- #
# Fake boto3 client
# --------------------------------------------------------------------------- #
class FakeS3Client:
    """Records calls to ``upload_fileobj`` / ``upload_file`` / ``head_object``.

    ``fail_times`` makes the first N upload attempts raise, so the retry loop can
    be exercised.
    """

    def __init__(self, fail_times: int = 0, head_exists: bool = True):
        self.fail_times = fail_times
        self.head_exists = head_exists
        self.upload_fileobj_calls = []
        self.upload_file_calls = []
        self.head_object_calls = []
        self._attempts = 0

    def _maybe_fail(self):
        if self._attempts < self.fail_times:
            self._attempts += 1
            raise RuntimeError("boom")

    def upload_fileobj(self, fileobj, bucket, key):
        self._maybe_fail()
        # Read the payload bytes eagerly so the test can assert on them.
        self.upload_fileobj_calls.append((fileobj.read(), bucket, key))

    def upload_file(self, filename, bucket, key):
        self._maybe_fail()
        self.upload_file_calls.append((filename, bucket, key))

    def head_object(self, Bucket, Key):
        self.head_object_calls.append((Bucket, Key))
        if not self.head_exists:
            raise RuntimeError("404")
        return {"ContentLength": 1}


# --------------------------------------------------------------------------- #
# NoopCloudSink
# --------------------------------------------------------------------------- #
def test_noop_is_cloud_sink():
    assert isinstance(NoopCloudSink(), CloudSink)


def test_noop_uploads_return_true():
    sink = NoopCloudSink()
    assert asyncio.run(sink.upload_bytes(b"x", "k")) is True
    assert asyncio.run(sink.upload_file(Path("/tmp/x"), "k")) is True
    assert asyncio.run(sink.register_api({"a": 1}, "action")) is True


def test_noop_key_exists_false():
    assert NoopCloudSink().key_exists("anything") is False


# --------------------------------------------------------------------------- #
# S3CloudSink — Protocol + unconfigured
# --------------------------------------------------------------------------- #
def test_s3_is_cloud_sink():
    sink = S3CloudSink(config={"aws_bucket": "b"})
    assert isinstance(sink, CloudSink)


def test_s3_unconfigured_uploads_noop_true():
    sink = S3CloudSink(config={"aws_bucket": "b"})
    assert sink.s3 is None
    assert asyncio.run(sink.upload_bytes(b"data", "k")) is True
    assert asyncio.run(sink.upload_file(Path("/tmp/f"), "k")) is True
    assert sink.key_exists("k") is False


def test_s3_unconfigured_register_api_true():
    sink = S3CloudSink(config={"aws_bucket": "b"})
    assert asyncio.run(sink.register_api({"x": 1}, "experiment")) is True


# --------------------------------------------------------------------------- #
# S3CloudSink — upload_bytes payload / content / key
# --------------------------------------------------------------------------- #
def test_s3_upload_bytes_payload_and_key():
    fake = FakeS3Client()
    sink = S3CloudSink(config={}, bucket="mybucket", client=fake)
    payload = json.dumps({"hello": "world"}).encode("utf-8")
    ok = asyncio.run(sink.upload_bytes(payload, "path/to/obj.json"))
    assert ok is True
    assert len(fake.upload_fileobj_calls) == 1
    sent_bytes, bucket, key = fake.upload_fileobj_calls[0]
    assert sent_bytes == payload
    assert bucket == "mybucket"
    assert key == "path/to/obj.json"


def test_s3_upload_bytes_gzip_appends_gz_and_compresses():
    fake = FakeS3Client()
    sink = S3CloudSink(config={}, bucket="b", client=fake)
    raw = b'{"k": "v"}'
    ok = asyncio.run(sink.upload_bytes(raw, "doc.json", compress=True))
    assert ok is True
    sent_bytes, _bucket, key = fake.upload_fileobj_calls[0]
    assert key == "doc.json.gz"
    # The sent bytes must be valid gzip that decompresses to the raw payload.
    assert gzip.decompress(sent_bytes) == raw


def test_s3_upload_bytes_gzip_keeps_existing_gz_suffix():
    fake = FakeS3Client()
    sink = S3CloudSink(config={}, bucket="b", client=fake)
    asyncio.run(sink.upload_bytes(b"abc", "already.gz", compress=True))
    _sent, _bucket, key = fake.upload_fileobj_calls[0]
    assert key == "already.gz"


# --------------------------------------------------------------------------- #
# S3CloudSink — upload_file
# --------------------------------------------------------------------------- #
def test_s3_upload_file_calls_upload_file():
    fake = FakeS3Client()
    sink = S3CloudSink(config={}, bucket="bkt", client=fake)
    ok = asyncio.run(sink.upload_file(Path("/some/local/file.hlo"), "remote/key.hlo"))
    assert ok is True
    assert fake.upload_file_calls == [("/some/local/file.hlo", "bkt", "remote/key.hlo")]
    assert fake.upload_fileobj_calls == []


# --------------------------------------------------------------------------- #
# S3CloudSink — retry loop
# --------------------------------------------------------------------------- #
def test_s3_upload_retries_then_succeeds(monkeypatch):
    sleeps = []

    async def fake_sleep(secs):
        sleeps.append(secs)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    fake = FakeS3Client(fail_times=2)
    sink = S3CloudSink(config={}, bucket="b", client=fake)
    ok = asyncio.run(sink.upload_bytes(b"data", "k"))
    assert ok is True
    # Two failures -> two 30s sleeps, third attempt succeeds.
    assert sleeps == [30, 30]
    assert len(fake.upload_fileobj_calls) == 1


def test_s3_upload_exhausts_retries_returns_false(monkeypatch):
    async def fake_sleep(secs):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    fake = FakeS3Client(fail_times=999)
    sink = S3CloudSink(config={}, bucket="b", client=fake)
    ok = asyncio.run(sink.upload_bytes(b"data", "k"))
    assert ok is False
    assert fake.upload_fileobj_calls == []


# --------------------------------------------------------------------------- #
# S3CloudSink — key_exists
# --------------------------------------------------------------------------- #
def test_s3_key_exists_true_via_head_object():
    fake = FakeS3Client(head_exists=True)
    sink = S3CloudSink(config={}, bucket="b", client=fake)
    assert sink.key_exists("k") is True
    assert fake.head_object_calls == [("b", "k")]


def test_s3_key_exists_false_when_head_raises():
    fake = FakeS3Client(head_exists=False)
    sink = S3CloudSink(config={}, bucket="b", client=fake)
    assert sink.key_exists("missing") is False


# --------------------------------------------------------------------------- #
# S3CloudSink — register_api
# --------------------------------------------------------------------------- #
def test_s3_register_api_no_api_host_true():
    fake = FakeS3Client()
    sink = S3CloudSink(config={}, bucket="b", client=fake)
    assert asyncio.run(sink.register_api({"a": 1}, "action")) is True


def test_s3_register_api_with_api_host_still_true():
    fake = FakeS3Client()
    sink = S3CloudSink(config={"api_host": "https://api.example"}, bucket="b", client=fake)
    # Legacy to_api never POSTs -- it always returns True.
    assert asyncio.run(sink.register_api({"a": 1}, "action")) is True


# --------------------------------------------------------------------------- #
# load_aws_config
# --------------------------------------------------------------------------- #
def test_load_aws_config_no_env_returns_copy(monkeypatch):
    monkeypatch.delenv("AWS_CONFIG_PATH", raising=False)
    cfg = {"aws_bucket": "b", "aws_profile": "p"}
    out = load_aws_config(cfg)
    assert out == cfg
    assert out is not cfg  # copy, not the same object


def test_load_aws_config_merges_profile(tmp_path, monkeypatch):
    aws_file = tmp_path / "aws_config"
    aws_file.write_text(
        "[myprofile]\n"
        "aws_access_key_id = AKIATEST\n"
        "aws_secret_access_key = secret123\n"
        "region = us-west-2\n"
    )
    monkeypatch.setenv("AWS_CONFIG_PATH", str(aws_file))
    cfg = {"aws_bucket": "b", "aws_profile": "myprofile"}
    out = load_aws_config(cfg)
    assert out["aws_access_key_id"] == "AKIATEST"
    assert out["aws_secret_access_key"] == "secret123"
    assert out["region"] == "us-west-2"
    assert out["aws_config_path"] == str(aws_file)
    assert out["aws_profile"] == "myprofile"
    # original untouched
    assert "aws_access_key_id" not in cfg


def test_load_aws_config_missing_profile_unchanged(tmp_path, monkeypatch):
    aws_file = tmp_path / "aws_config"
    aws_file.write_text("[default]\naws_access_key_id = X\n")
    monkeypatch.setenv("AWS_CONFIG_PATH", str(aws_file))
    cfg = {"aws_bucket": "b", "aws_profile": "absent"}
    out = load_aws_config(cfg)
    assert "aws_access_key_id" not in out
    assert out["aws_bucket"] == "b"


# --------------------------------------------------------------------------- #
# dict2json
# --------------------------------------------------------------------------- #
def test_dict2json_roundtrip():
    d = {"a": 1, "b": ["x", "y"], "c": {"nested": True}}
    bio = dict2json(d)
    assert isinstance(bio, io.BytesIO)
    data = bio.read()
    assert json.loads(data.decode("utf-8")) == d


def test_dict2json_is_rewound():
    bio = dict2json({"k": "v"})
    assert bio.tell() == 0
