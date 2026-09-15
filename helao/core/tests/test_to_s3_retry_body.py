"""``to_s3`` must send a whole body on a retry, not whatever boto3 left.

``upload_fileobj`` consumes the buffer it is handed and s3transfer's cleanup
may close it, so a retry that reused the same object uploaded a truncated
body -- and returned True for it.
"""

import asyncio
import json

from helao.core.drivers.data.sync_driver import SyncDriver
from helao.hexagon.tests.sync_fixtures import make_sync_driver, teardown_driver

MSG = {"payload": list(range(50))}


class _FlakyS3:
    """Consumes (and closes) the body on a failed attempt, as boto3 does."""

    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.attempts = 0
        self.received: bytes = b""

    def upload_fileobj(self, fileobj, bucket, key):
        self.attempts += 1
        if self.attempts <= self.fail_times:
            fileobj.read(4)  # a partial transfer
            fileobj.close()
            raise RuntimeError("boom")
        self.received = fileobj.read()

    def upload_file(self, path, bucket, key):
        self.attempts += 1
        self.received = open(path, "rb").read()


def _run(tmp_path, monkeypatch, client, msg, **kw):
    real_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda *_: real_sleep(0))

    async def _go():
        driver = make_sync_driver(tmp_path, SyncDriver)
        driver.s3 = client
        try:
            return await driver.to_s3(msg, "meta/x.json", **kw)
        finally:
            await teardown_driver(driver)

    return asyncio.run(_go())


def test_a_retry_sends_the_whole_dict_body(tmp_path, monkeypatch):
    client = _FlakyS3(fail_times=2)
    assert _run(tmp_path, monkeypatch, client, MSG) is True
    assert client.attempts == 3
    assert json.loads(client.received) == MSG


def test_the_first_attempt_still_sends_the_whole_dict_body(tmp_path, monkeypatch):
    client = _FlakyS3(fail_times=0)
    assert _run(tmp_path, monkeypatch, client, MSG) is True
    assert client.attempts == 1
    assert json.loads(client.received) == MSG


def test_a_file_path_upload_is_unchanged(tmp_path, monkeypatch):
    src = tmp_path / "blob.bin"
    src.write_bytes(b"0123456789")
    client = _FlakyS3(fail_times=0)
    assert _run(tmp_path, monkeypatch, client, src) is True
    assert client.received == b"0123456789"


def test_a_compressed_body_is_gzip_on_every_attempt(tmp_path, monkeypatch):
    import gzip

    client = _FlakyS3(fail_times=1)
    assert _run(tmp_path, monkeypatch, client, MSG, compress=True) is True
    assert client.attempts == 2
    assert json.loads(gzip.decompress(client.received)) == MSG
