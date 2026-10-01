"""The DB endpoint surface, pinned on both drivers that can serve it (B7b).

Moved from ``test_sync_graft.test_native_driver_exposes_db_endpoint_surface``
when the sync graft was deleted (D-B7b.6). The test deployment's
``sim_db_server`` endpoints resolve ``app.driver`` at call time, so these
attributes are the endpoint contract: ``enqueue_yml``, ``list_pending``,
``finish_pending`` (with the ``actions_first`` keyword the harness posts),
``reset_sync``, ``running_tasks`` and ``task_queue``. ``progress`` is
deliberately absent on both (its assignment is commented out), so
``/current_progress`` raising AttributeError is pre-existing behaviour, pinned
here so nobody "fixes" it by accident.

Two drivers: the ``NativeSyncer`` the graft used to bind, and the
``SimHelaoSyncer`` the ``ActionHost`` builds in its own startup event, which is
what the endpoints resolve now that nothing rebinds ``app.driver``. The
recorder injection the graft replicated is pinned on the latter as well.
"""

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from helao.core.models.helaodirs import HelaoDirs
from helao.core.models.run_dir import RunDir
from helao.hexagon.tests.sync_fixtures import teardown_driver

PARAMS = {"aws_bucket": "helao-sim", "max_tasks": 1}


@pytest.fixture(autouse=True)
def _hermetic_aws(monkeypatch):
    monkeypatch.delenv("AWS_CONFIG_PATH", raising=False)


async def _native_syncer(tmp_path, monkeypatch):
    from helao.hexagon.adapters.native.native_syncer import NativeSyncer

    host = SimpleNamespace(
        server_cfg={"params": dict(PARAMS)},
        world_cfg={"servers": {"SYNC": {"params": dict(PARAMS)}}},
        helaodirs=HelaoDirs(
            root=Path(tmp_path),
            save_root=Path(tmp_path) / RunDir.ACTIVE.value,
            process_root=Path(tmp_path) / "PROCESSES",
        ),
    )
    drv = NativeSyncer(host)  # type: ignore[arg-type]  # duck-typed SyncerHost

    async def _teardown():
        await teardown_driver(drv)

    return drv, _teardown


async def _action_host_driver(tmp_path, monkeypatch, params=None):
    """Run only ActionHost's own startup handler: it builds the driver.

    The full startup list also binds the co-located RPC socket, which this
    test does not need and must not hold.
    """
    from helao.deploy.test.servers.action.sim_db_server import makeApp
    from helao.helpers import config_loader

    (tmp_path / "LOGS").mkdir()
    monkeypatch.setattr(
        config_loader,
        "CONFIG",
        {
            "root": str(tmp_path),
            "dummy": True,
            "simulation": True,
            "servers": {
                "SYNC": {
                    "host": "127.0.0.1",
                    "port": 8910,
                    "group": "action",
                    "fast": "sim_db_server",
                    "params": dict(PARAMS if params is None else params),
                }
            },
        },
    )
    app = makeApp("SYNC")
    (startup,) = [h for h in app.router.on_startup if h.__name__ == "startup_event"]
    startup()
    drv = app.driver

    async def _teardown():
        await teardown_driver(drv)
        await app.shutdown()

    return drv, _teardown


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "build", [_native_syncer, _action_host_driver], ids=["NativeSyncer", "ActionHost"]
)
async def test_the_driver_exposes_the_db_endpoint_surface(build, tmp_path, monkeypatch):
    drv, teardown = await build(tmp_path, monkeypatch)
    try:
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
        assert not hasattr(drv, "progress")
    finally:
        await teardown()


@pytest.mark.asyncio
@pytest.mark.parametrize("s3_record", [True, False])
async def test_the_action_host_driver_records_s3_only_when_asked(
    s3_record, tmp_path, monkeypatch
):
    """The graft used to replicate SimHelaoSyncer's recorder injection; the
    driver the endpoints now resolve must do it itself (sim_db_server.py:82-86).
    """
    from helao.deploy.test.servers.action.sim_db_server import RecordingS3Client

    params = dict(PARAMS, s3_record=True) if s3_record else dict(PARAMS)
    drv, teardown = await _action_host_driver(tmp_path, monkeypatch, params)
    try:
        if s3_record:
            assert isinstance(drv.s3, RecordingS3Client)
            assert drv.s3.sim_root == Path(tmp_path) / "S3_SIM"
        else:
            assert not isinstance(drv.s3, RecordingS3Client)
    finally:
        await teardown()
