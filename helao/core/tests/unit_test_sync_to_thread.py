"""Unit test for the off-loop (``asyncio.to_thread``) sync I/O in sync_driver.

``HelaoSyncer``/``SyncDriver`` run their ``syncer`` worker coroutines on the
hosting FastAPI server's event loop. The heavy steps in ``sync_yml`` --
boto3 S3 uploads, ``read_hlo``/``hlo_to_parquet`` parsing, ``zip_dir``, and
file moves -- are blocking; if they run inline they freeze the loop and the
whole server (every endpoint) times out until they finish. Those call sites
are wrapped in ``asyncio.to_thread`` so the loop stays responsive.

This test guards that contract. It drives the real changed code paths and
runs a heartbeat coroutine concurrently to measure the worst loop-stall:

  * ``to_s3`` with a deliberately blocking boto3-style client must offload
    the upload (heartbeat keeps ticking while the upload sleeps),
  * ``to_s3`` with S3 disabled (``s3 is None``) is a no-op returning ``True``,
  * the real ``move_to_synced`` + ``zip_dir`` helpers invoked via
    ``asyncio.to_thread`` complete and keep the loop responsive.

The test is hermetic: ``AWS_CONFIG_PATH`` is unset for the duration so the
driver never reads host credentials or contacts S3, regardless of where the
runner executes (it gates ``launch.py``).
"""

__all__ = ["sync_to_thread_unit_test"]

import asyncio
import os
import tempfile
import time
import traceback
from pathlib import Path

from helao.core.tests._test_utils import TestReporter
from helao.core.drivers.data.sync_driver import SyncDriver, move_to_synced
from helao.helpers.file_utils import zip_dir
from helao.core.models.helaodirs import HelaoDirs
from helao.core.models.run_dir import RunDir

# Blocking duration injected into the fake uploader. The "responsive" check
# asserts the loop stall stayed well under this; a regression that drops the
# to_thread offload would stall the loop for ~BLOCK_S and fail the check.
BLOCK_S = 0.5
# Generous ceiling: tiny when offloaded, ~BLOCK_S when run inline. Set to half
# of BLOCK_S so host scheduling jitter never trips a false failure while a real
# regression (full inline block) still fails cleanly.
MAX_GAP_S = BLOCK_S / 2


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


def _make_driver(tmp_root: str) -> SyncDriver:
    """Build a SyncDriver with no AWS/API configured (``s3``/``api_host`` None)."""
    hd = HelaoDirs(
        root=Path(tmp_root),
        save_root=Path(tmp_root) / RunDir.ACTIVE.value,
        process_root=Path(tmp_root) / "PROCESSES",
    )
    cfg = {"aws_bucket": "test-bucket", "max_tasks": 1}
    return SyncDriver(cfg, hd)


async def _run_checks() -> dict:
    """Drive the changed code paths and return a dict of named boolean results."""
    out = {}
    with tempfile.TemporaryDirectory() as tmp_root:
        drv = _make_driver(tmp_root)
        try:
            out["s3_none"] = drv.s3 is None
            out["api_none"] = drv.api_host is None

            # no-op S3 path (s3 is None) returns True
            out["to_s3_noop_true"] = (
                await drv.to_s3({"k": "v"}, "meta/x.json")
            ) is True

            # blocking upload must run off-loop
            drv.s3 = _BlockingS3()
            drv.bucket = "test-bucket"
            hb = _HeartBeat()
            hb_task = asyncio.create_task(hb.run())
            t0 = time.perf_counter()
            ok = await drv.to_s3({"payload": list(range(1000))}, "meta/blob.json")
            elapsed = time.perf_counter() - t0
            hb.stop()
            await hb_task
            out["to_s3_returned_true"] = ok is True
            out["uploader_ran"] = drv.s3.calls == 1
            out["upload_took_block_time"] = elapsed >= BLOCK_S * 0.9
            out["loop_responsive_upload"] = hb.max_gap < MAX_GAP_S

            # real move_to_synced + zip_dir via to_thread
            fin = (
                Path(tmp_root)
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
            out["move_returned_path"] = isinstance(moved, Path)
            out["moved_into_synced"] = (
                isinstance(moved, Path)
                and RunDir.SYNCED in str(moved)
                and moved.exists()
            )
            out["moved_out_of_finished"] = not data.exists()

            synced_dir = Path(
                str(fin).replace(RunDir.FINISHED.value, RunDir.SYNCED.value)
            )
            await asyncio.to_thread(move_to_synced, seq_yml)
            zip_target = synced_dir.parent / f"{synced_dir.name}.zip"
            await asyncio.to_thread(zip_dir, synced_dir, zip_target)
            hb.stop()
            await hb_task
            out["zip_created"] = zip_target.exists() and zip_target.stat().st_size > 0
            out["loop_responsive_move_zip"] = hb.max_gap < MAX_GAP_S
        finally:
            # tear down the background syncer worker(s) created in __init__
            for task in drv.syncer_loops.values():
                task.cancel()
            await asyncio.gather(*drv.syncer_loops.values(), return_exceptions=True)
    return out


def sync_to_thread_unit_test() -> bool:
    """Run all sync-driver off-loop assertions and report pass/fail."""
    reporter = TestReporter("sync_to_thread")

    # Hermetic: never read host AWS credentials or hit S3 during the test.
    saved_aws = os.environ.pop("AWS_CONFIG_PATH", None)
    try:
        res = asyncio.run(_run_checks())
    except Exception as exc:  # noqa: BLE001
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        print(repr(exc), tb)
        return False
    finally:
        if saved_aws is not None:
            os.environ["AWS_CONFIG_PATH"] = saved_aws

    reporter.section("SyncDriver construction (S3/API disabled)")
    reporter.check("s3 client is None when unconfigured", lambda: res["s3_none"])
    reporter.check("api_host is None when unconfigured", lambda: res["api_none"])

    reporter.section("to_s3 no-op path")
    reporter.check(
        "to_s3 returns True when S3 disabled", lambda: res["to_s3_noop_true"]
    )

    reporter.section("to_s3 offloads blocking upload")
    reporter.check(
        "to_s3 returns True after upload", lambda: res["to_s3_returned_true"]
    )
    reporter.check("blocking uploader actually ran", lambda: res["uploader_ran"])
    reporter.check(
        "upload spent the full block time", lambda: res["upload_took_block_time"]
    )
    reporter.check(
        "event loop stayed responsive during upload (offloaded)",
        lambda: res["loop_responsive_upload"],
    )

    reporter.section("move_to_synced + zip_dir via to_thread")
    reporter.check("move_to_synced returned a Path", lambda: res["move_returned_path"])
    reporter.check("file moved into RUNS_SYNCED", lambda: res["moved_into_synced"])
    reporter.check(
        "file removed from RUNS_FINISHED", lambda: res["moved_out_of_finished"]
    )
    reporter.check("sequence zip created", lambda: res["zip_created"])
    reporter.check(
        "event loop stayed responsive during move+zip",
        lambda: res["loop_responsive_move_zip"],
    )

    return reporter.success()


if __name__ == "__main__":
    import sys

    sys.exit(0 if sync_to_thread_unit_test() else 1)
