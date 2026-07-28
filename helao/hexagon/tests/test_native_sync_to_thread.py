"""Port of unit_test_sync_to_thread.py onto the NATIVE SyncDriver (P2c T10).

``HelaoSyncer``/``SyncDriver`` run their ``syncer`` worker coroutines on the
hosting FastAPI server's event loop. The heavy steps in ``sync_yml`` --
boto3 S3 uploads, ``read_hlo``/``hlo_to_parquet`` parsing, ``zip_dir``, and
file moves -- are blocking; if they run inline they freeze the loop and the
whole server (every endpoint) times out until they finish. Those call sites
are wrapped in ``asyncio.to_thread`` so the loop stays responsive.

This test guards that contract against the NATIVE driver. It drives the real
changed code paths and runs a heartbeat coroutine concurrently to measure the
worst loop-stall:

  * ``to_s3`` with a deliberately blocking boto3-style client must offload
    the upload (heartbeat keeps ticking while the upload sleeps),
  * ``to_s3`` with S3 disabled (``s3 is None``) is a no-op returning ``True``,
  * the real ``move_to_synced`` + ``zip_dir`` helpers invoked via
    ``asyncio.to_thread`` complete and keep the loop responsive.

The legacy test file is NOT modified and NOT imported for logic (mirrored
only). Mechanical translation: legacy `_make_driver` -> `make_sync_driver(...,
NativeSyncDriver)`, legacy `tempfile.TemporaryDirectory()` -> pytest
`tmp_path`, legacy `out["key"] = expr` -> `assert expr, "key"`."""

import asyncio
import time
from pathlib import Path

import pytest

from helao.hexagon.adapters.native.sync_driver import (
    SyncDriver as NativeSyncDriver,
    move_to_synced,
)
from helao.helpers.file_utils import zip_dir
from helao.core.models.run_dir import RunDir
from helao.hexagon.tests.sync_fixtures import make_sync_driver, teardown_driver

# Blocking duration injected into the fake uploader. The "responsive" check
# asserts the loop stall stayed well under this; a regression that drops the
# to_thread offload would stall the loop for ~BLOCK_S and fail the check.
BLOCK_S = 0.5
# Generous ceiling: tiny when offloaded, ~BLOCK_S when run inline. Set to half
# of BLOCK_S so host scheduling jitter never trips a false failure while a real
# regression (full inline block) still fails cleanly.
MAX_GAP_S = BLOCK_S / 2


@pytest.fixture(autouse=True)
def _hermetic_aws(monkeypatch):
    monkeypatch.delenv("AWS_CONFIG_PATH", raising=False)


class _HeartBeat:
    """Tracks the worst gap between ticks of a fixed-interval loop sleeper."""

    def __init__(self, interval: float = 0.01):
        self.interval = interval
        self.max_gap = 0.0
        self._stop = False

    async def run(self):
        last = time.perf_counter()
        while not self._stop:
            await asyncio.sleep(self.interval)
            now = time.perf_counter()
            self.max_gap = max(self.max_gap, now - last)
            last = now

    def stop(self):
        self._stop = True


class _BlockingS3:
    """boto3-client stand-in whose upload BLOCKS the calling thread."""

    def __init__(self, block_s: float = BLOCK_S):
        self.block_s = block_s
        self.calls = 0

    def _block(self, *args, **kwargs):
        time.sleep(self.block_s)  # like real boto3 network I/O
        self.calls += 1

    upload_fileobj = _block
    upload_file = _block


# --- 1. construction + no-op S3 path ---------------------------------------


@pytest.mark.asyncio
async def test_construction_and_noop_s3(tmp_path):
    drv = make_sync_driver(str(tmp_path), NativeSyncDriver)
    try:
        assert drv.s3 is None, "s3_none"

        # no-op S3 path (s3 is None) returns True
        assert (await drv.to_s3({"k": "v"}, "meta/x.json")) is True, "to_s3_noop_true"
    finally:
        await teardown_driver(drv)


# --- 2. blocking upload must run off-loop -----------------------------------


@pytest.mark.asyncio
async def test_to_s3_offloads_blocking_upload(tmp_path):
    drv = make_sync_driver(str(tmp_path), NativeSyncDriver)
    try:
        drv.s3 = _BlockingS3()
        drv.bucket = "test-bucket"
        hb = _HeartBeat()
        hb_task = asyncio.create_task(hb.run())
        t0 = time.perf_counter()
        ok = await drv.to_s3({"payload": list(range(1000))}, "meta/blob.json")
        elapsed = time.perf_counter() - t0
        hb.stop()
        await hb_task

        assert ok is True, "to_s3_returned_true"
        assert drv.s3.calls == 1, "uploader_ran"
        assert elapsed >= BLOCK_S * 0.9, "upload_took_block_time"
        assert hb.max_gap < MAX_GAP_S, "loop_responsive_upload"
    finally:
        await teardown_driver(drv)


# --- 3. real move_to_synced + zip_dir via to_thread -------------------------


@pytest.mark.asyncio
async def test_move_and_zip_offload_keep_loop_responsive(tmp_path):
    drv = make_sync_driver(str(tmp_path), NativeSyncDriver)
    try:
        fin = (
            Path(tmp_path)
            / RunDir.FINISHED.value
            / "26.23"
            / "0610"
            / "120000__seq__lab"
        )
        fin.mkdir(parents=True)
        seq_yml = fin / "260610.120000000000-seq.yml"
        seq_yml.write_text("sequence_name: seq\n", encoding="utf-8")
        data = fin / "data.hlo"
        data.write_bytes(b"x" * (5 * 1024 * 1024))  # 5 MB, real move/zip work

        hb = _HeartBeat()
        hb_task = asyncio.create_task(hb.run())
        moved = await asyncio.to_thread(move_to_synced, data)
        assert isinstance(moved, Path), "move_returned_path"
        assert (
            isinstance(moved, Path) and RunDir.SYNCED in str(moved) and moved.exists()
        ), "moved_into_synced"
        assert not data.exists(), "moved_out_of_finished"

        synced_dir = Path(str(fin).replace(RunDir.FINISHED.value, RunDir.SYNCED.value))
        await asyncio.to_thread(move_to_synced, seq_yml)
        zip_target = synced_dir.parent / f"{synced_dir.name}.zip"
        await asyncio.to_thread(zip_dir, synced_dir, zip_target)
        hb.stop()
        await hb_task

        assert zip_target.exists() and zip_target.stat().st_size > 0, "zip_created"
        assert hb.max_gap < MAX_GAP_S, "loop_responsive_move_zip"
    finally:
        await teardown_driver(drv)
