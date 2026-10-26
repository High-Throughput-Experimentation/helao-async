"""NativeSyncer (D2: the syncer's config resolution sans Base) +
NativeSyncAdapter (SyncPort conformance + delegation) + the negative: sync stays
OUT of the REQUIRED wiring sets, because it is bound at startup."""

from pathlib import Path
from types import SimpleNamespace

import os

import pytest

from helao.core.models.helaodirs import HelaoDirs
from helao.core.models.run_dir import RunDir
from helao.hexagon.adapters.native.native_syncer import NativeSyncer
from helao.hexagon.adapters.native.sync_adapter import NativeSyncAdapter
from helao.hexagon.app.wiring import ACTION_REQUIRED, ORCH_REQUIRED
from helao.hexagon.ports.sync import SyncPort
from helao.hexagon.tests.sync_fixtures import teardown_driver


@pytest.fixture(autouse=True)
def _hermetic_aws(monkeypatch):
    monkeypatch.delenv("AWS_CONFIG_PATH", raising=False)


def _host(tmp_path, local_params, world_db_params):
    hd = HelaoDirs(
        root=Path(tmp_path),
        save_root=Path(tmp_path) / RunDir.ACTIVE.value,
        process_root=Path(tmp_path) / "PROCESSES",
    )
    return SimpleNamespace(
        server_cfg={"params": local_params},
        world_cfg={"servers": {"SYNC": {"params": world_db_params}}},
        helaodirs=hd,
    )


@pytest.mark.asyncio
async def test_falls_back_to_db_params_without_aws_config_path(tmp_path):
    """The syncer's config semantics (NativeSyncer.__init__): local params lacking
    aws_config_path + DB present in world servers -> DB params win."""
    host = _host(
        tmp_path,
        local_params={"aws_bucket": "local-bucket", "max_tasks": 1},
        world_db_params={"aws_bucket": "db-bucket", "max_tasks": 1},
    )
    syncer = NativeSyncer(host)  # type: ignore[reportArgumentType]
    try:
        assert syncer.bucket == "db-bucket"
        assert syncer.s3 is None
    finally:
        await teardown_driver(syncer)


@pytest.mark.asyncio
async def test_keeps_local_params_with_aws_config_path(tmp_path, monkeypatch):
    # Record the true pre-test state (absent) so teardown restores "absent":
    # __init__ sets AWS_CONFIG_PATH raw, and a delenv issued after that would
    # make monkeypatch restore the temporary value at teardown.
    monkeypatch.delenv("AWS_CONFIG_PATH", raising=False)
    aws_cfg = tmp_path / "aws.ini"
    aws_cfg.write_text("[default]\n", encoding="utf-8")
    host = _host(
        tmp_path,
        local_params={
            "aws_bucket": "local-bucket",
            "max_tasks": 1,
            "aws_config_path": str(aws_cfg),
            "aws_access_key_id": "x",
            "aws_secret_access_key": "y",
            "region": "us-west-1",
        },
        world_db_params={"aws_bucket": "db-bucket"},
    )
    syncer = NativeSyncer(host)  # type: ignore[reportArgumentType]
    try:
        assert syncer.bucket == "local-bucket"  # local params kept
        assert syncer.s3 is not None  # boto3 client built, never contacted
    finally:
        await teardown_driver(syncer)
        os.environ.pop("AWS_CONFIG_PATH", None)  # __init__ set it


@pytest.mark.asyncio
async def test_adapter_is_sync_port_and_delegates(tmp_path):
    # world_db_params carries a stub aws_bucket: _host() always inserts a
    # "SYNC" world-server entry, so an empty dict here would still trigger the
    # (legacy-identical) no-aws_config_path fallback in NativeSyncer.__init__
    # and crash on the required aws_bucket lookup -- this test only cares
    # about adapter delegation, not config-fallback semantics (covered above).
    host = _host(tmp_path, {"aws_bucket": "b", "max_tasks": 1}, {"aws_bucket": "b"})
    syncer = NativeSyncer(host)  # type: ignore[reportArgumentType]
    adapter = NativeSyncAdapter(syncer)
    # stop workers so queue contents stay observable
    await teardown_driver(syncer)
    assert isinstance(adapter, SyncPort)
    assert adapter.n_queue() == 0
    await adapter.enqueue_yml(tmp_path / "RUNS_FINISHED" / "a-seq.yml", rank=2)
    assert adapter.n_queue() == 1
    assert adapter.reset_sync(str(tmp_path / "nope")) is False
    assert adapter.list_pending() == []


def test_sync_is_not_a_required_port():
    """Bound at startup (the syncer needs a running loop), and an orchestrator
    with no SYNC server runs without one."""
    assert "sync" not in ORCH_REQUIRED
    assert "sync" not in ACTION_REQUIRED
