"""Native SyncDriver core behavior (P2c T4): hermetic construction (s3/api
None, worker tasks spawned), enqueue dedup, and the rank floor. Mirrors the
construction contract proven by unit_test_sync_to_thread.py:87-95."""

from pathlib import Path

import pytest

from helao.hexagon.adapters.native.sync_driver import SyncDriver as NativeSyncDriver
from helao.hexagon.tests.sync_fixtures import make_sync_driver, teardown_driver


@pytest.fixture(autouse=True)
def _hermetic_aws(monkeypatch):
    monkeypatch.delenv("AWS_CONFIG_PATH", raising=False)


@pytest.mark.asyncio
async def test_construction_hermetic(tmp_path):
    drv = make_sync_driver(str(tmp_path), NativeSyncDriver)
    try:
        assert drv.s3 is None and drv.s3r is None and drv.aws_session is None
        assert drv.api_host is None
        assert drv.bucket == "test-bucket"
        assert drv.task_queue.qsize() == 0
        assert len(drv.syncer_loops) == 1  # max_tasks=1
        assert all(not t.done() for t in drv.syncer_loops.values())
    finally:
        await teardown_driver(drv)


@pytest.mark.asyncio
async def test_enqueue_dedup_and_rank_floor(tmp_path):
    drv = make_sync_driver(str(tmp_path), NativeSyncDriver)
    # stop the workers FIRST so enqueued items stay observable
    await teardown_driver(drv)
    yml = Path(tmp_path) / "RUNS_FINISHED" / "x" / "260610.120000000000-seq.yml"
    await drv.enqueue_yml(yml, rank=2)
    await drv.enqueue_yml(yml, rank=2)  # dedup via task_set
    assert drv.task_queue.qsize() == 1
    other = yml.parent / "260610.120000000001-seq.yml"
    await drv.enqueue_yml(other, rank=-6)  # below rank_limit=-5 -> dropped
    assert drv.task_queue.qsize() == 1
