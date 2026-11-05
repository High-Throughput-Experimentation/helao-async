"""AWS credentials must never land in the live world config.

``SyncDriver`` merges the INI named by ``AWS_CONFIG_PATH`` for its own use.
``ActionHost``'s private ``/get_config`` route serves ``world_cfg``, and the
driver's ``config`` is the same dict object as
``world_cfg["servers"][key]["params"]``, so a merge into it publishes the
secret. Both twins are checked, plus ``NativeSyncer``'s shared-dict path.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from helao.core.models.helaodirs import HelaoDirs
from helao.core.models.run_dir import RunDir
from helao.hexagon.adapters.native.sync_driver import SyncDriver as NativeSyncDriver
from helao.hexagon.tests.sync_fixtures import teardown_driver

SENTINEL = "SECRET-SENTINEL"
KEY_ID = "KEYID-SENTINEL"


@pytest.fixture
def aws_ini(tmp_path, monkeypatch):
    ini = tmp_path / "aws.ini"
    ini.write_text(
        "[default]\n"
        f"aws_access_key_id = {KEY_ID}\n"
        f"aws_secret_access_key = {SENTINEL}\n"
        "region = us-west-2\n"
        "aws_bucket = ini-bucket\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AWS_CONFIG_PATH", str(ini))
    return ini


def _dirs(tmp_path):
    return HelaoDirs(
        root=Path(tmp_path),
        save_root=Path(tmp_path) / RunDir.ACTIVE.value,
        process_root=Path(tmp_path) / "PROCESSES",
    )


def _assert_clean(world_cfg, ini):
    dumped = json.dumps(world_cfg)
    for leaked in (SENTINEL, KEY_ID, "aws_secret_access_key", str(ini)):
        assert leaked not in dumped


@pytest.mark.asyncio
@pytest.mark.parametrize("cls", [NativeSyncDriver])
async def test_driver_keeps_secrets_out_of_params(cls, tmp_path, aws_ini):
    params = {"max_tasks": 1}
    world_cfg = {"servers": {"SYNC": {"params": params}}}
    drv = cls(params, _dirs(tmp_path))
    try:
        _assert_clean(world_cfg, aws_ini)
        assert drv.s3 is not None
        assert drv.bucket == "ini-bucket"
    finally:
        await teardown_driver(drv)


@pytest.mark.asyncio
async def test_native_syncer_keeps_secrets_out_of_world_cfg(tmp_path, aws_ini):
    from helao.hexagon.adapters.native.native_syncer import NativeSyncer

    params = {"max_tasks": 1}
    host = SimpleNamespace(
        server_cfg={"params": params},
        world_cfg={"servers": {"SYNC": {"params": params}}},
        helaodirs=_dirs(tmp_path),
    )
    drv = NativeSyncer(host)  # type: ignore[arg-type]
    try:
        _assert_clean(host.world_cfg, aws_ini)
        assert drv.s3 is not None
        assert drv.bucket == "ini-bucket"
    finally:
        await teardown_driver(drv)
