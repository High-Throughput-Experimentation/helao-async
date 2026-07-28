"""P2e sync graft (D1): cancel the legacy driver's orphaned syncer loops,
construct a raw NativeSyncer against the SyncerHost duck-type, replicate the
RecordingS3Client injection for s3_record, and rebind app.driver. The DB
endpoints (sim_db_server.py:111-151) read app.driver exclusively, so the
rebind is the whole cut-over; the launched GM-5 gate (Task 4) is the proof."""

import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from helao.core.models.helaodirs import HelaoDirs
from helao.core.models.run_dir import RunDir
from helao.deploy.test.servers.action.sim_db_server import RecordingS3Client
from helao.hexagon.adapters.native.native_syncer import NativeSyncer
from helao.hexagon.tests.sync_fixtures import teardown_driver

PARAMS = {"aws_bucket": "helao-sim", "max_tasks": 1}


@pytest.fixture(autouse=True)
def _hermetic_aws(monkeypatch):
    monkeypatch.delenv("AWS_CONFIG_PATH", raising=False)


def _fake_base(tmp_path, params):
    """Duck-typed Base: SyncerHost surface + the .app back-ref (base.py:139)."""
    hd = HelaoDirs(
        root=Path(tmp_path),
        save_root=Path(tmp_path) / RunDir.ACTIVE.value,
        process_root=Path(tmp_path) / "PROCESSES",
    )
    app = SimpleNamespace(driver=None)
    base = SimpleNamespace(
        app=app,
        server_cfg={"params": params},
        world_cfg={"servers": {"SYNC": {"params": params}}},
        helaodirs=hd,
    )
    return base, app


async def _fake_legacy_driver():
    """Stands in for the SimHelaoSyncer BaseAPI startup already built: the
    only surface the graft touches is .syncer_loops (real blocked tasks)."""
    blocker = asyncio.Event()
    loops = {i: asyncio.create_task(blocker.wait()) for i in range(2)}
    return SimpleNamespace(syncer_loops=loops), loops


@pytest.mark.asyncio
async def test_graft_rebinds_driver_and_cancels_legacy_loops(tmp_path):
    from helao.hexagon.app.sync_graft import NativeSyncGraft, graft_native_sync

    base, app = _fake_base(tmp_path, dict(PARAMS))
    old_driver, old_loops = await _fake_legacy_driver()
    app.driver = old_driver

    handle = graft_native_sync(base, dict(PARAMS))
    try:
        assert isinstance(handle, NativeSyncGraft)
        assert isinstance(app.driver, NativeSyncer)
        assert app.driver is handle.native
        assert handle.originals["driver"] is old_driver
        # orphan fix: every pre-existing worker loop is cancelled
        results = await asyncio.gather(*old_loops.values(), return_exceptions=True)
        assert all(isinstance(r, asyncio.CancelledError) for r in results)
    finally:
        await teardown_driver(app.driver)


@pytest.mark.asyncio
async def test_graft_injects_recording_s3_when_s3_record(tmp_path):
    from helao.hexagon.app.sync_graft import graft_native_sync

    params = dict(PARAMS, s3_record=True)
    base, app = _fake_base(tmp_path, params)
    old_driver, _ = await _fake_legacy_driver()
    app.driver = old_driver

    graft_native_sync(base, params)
    try:
        assert isinstance(app.driver.s3, RecordingS3Client)
        # mirrors SimHelaoSyncer.__init__ (sim_db_server.py:81-85)
        assert app.driver.s3.sim_root == Path(tmp_path) / "S3_SIM"
    finally:
        await teardown_driver(app.driver)


@pytest.mark.asyncio
async def test_graft_leaves_s3_none_without_s3_record(tmp_path):
    from helao.hexagon.app.sync_graft import graft_native_sync

    base, app = _fake_base(tmp_path, dict(PARAMS))
    old_driver, _ = await _fake_legacy_driver()
    app.driver = old_driver

    graft_native_sync(base, dict(PARAMS))
    try:
        assert app.driver.s3 is None  # local-only mode (sync completes locally)
    finally:
        await teardown_driver(app.driver)


@pytest.mark.asyncio
async def test_native_driver_exposes_db_endpoint_surface(tmp_path):
    """Every attribute the DB endpoints resolve on app.driver
    (sim_db_server.py:111-146) must exist on the grafted native instance;
    finish_pending must keep the actions_first kwarg the harness posts."""
    from helao.hexagon.app.sync_graft import graft_native_sync

    base, app = _fake_base(tmp_path, dict(PARAMS))
    old_driver, _ = await _fake_legacy_driver()
    app.driver = old_driver

    graft_native_sync(base, dict(PARAMS))
    try:
        drv = app.driver
        for attr in (
            "enqueue_yml",
            "list_pending",
            "finish_pending",
            "reset_sync",
            "running_tasks",
            "task_queue",
        ):
            assert hasattr(drv, attr), attr
        assert "actions_first" in inspect.signature(drv.finish_pending).parameters
        assert drv.task_queue.qsize() == 0
        assert drv.running_tasks == {}
        # NOTE: `progress` is deliberately ABSENT on both stacks
        # (assignment commented out) — /current_progress AttributeError is
        # pre-existing legacy behavior, pinned here so nobody "fixes" it.
        assert not hasattr(drv, "progress")
    finally:
        await teardown_driver(app.driver)


@pytest.mark.asyncio
async def test_graft_close_restores_original_driver(tmp_path):
    from helao.hexagon.app.sync_graft import graft_native_sync

    base, app = _fake_base(tmp_path, dict(PARAMS))
    old_driver, _ = await _fake_legacy_driver()
    app.driver = old_driver

    handle = graft_native_sync(base, dict(PARAMS))
    native = handle.native
    handle.close()
    assert app.driver is old_driver
    results = await asyncio.gather(
        *native.syncer_loops.values(), return_exceptions=True
    )
    assert all(isinstance(r, asyncio.CancelledError) for r in results)


@pytest.mark.asyncio
async def test_graft_fails_loud_without_live_legacy_driver(tmp_path):
    """Startup-order guard: if BaseAPI's own startup has not populated
    app.driver, the graft must abort loudly, never bind over nothing."""
    from helao.hexagon.app.sync_graft import graft_native_sync

    base, app = _fake_base(tmp_path, dict(PARAMS))
    assert app.driver is None
    with pytest.raises(RuntimeError, match="app.driver"):
        graft_native_sync(base, dict(PARAMS))
