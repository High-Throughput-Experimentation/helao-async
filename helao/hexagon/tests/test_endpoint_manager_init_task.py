"""``dyn_endpoints_init`` must keep its task and surface its failure."""

import asyncio
import logging
from types import SimpleNamespace

import pytest

from helao.hexagon.app.endpoint_manager import EndpointManager


@pytest.mark.asyncio
async def test_init_task_is_held_and_its_failure_is_logged(caplog):
    mgr = EndpointManager(SimpleNamespace(_dyn_endpoints=None))

    async def boom(dyn_endpoints=None):
        raise RuntimeError("init exploded")

    mgr.init_endpoint_status = boom
    caplog.set_level(logging.ERROR)
    mgr.dyn_endpoints_init()
    assert isinstance(mgr._init_task, asyncio.Future)
    await asyncio.wait({mgr._init_task})
    await asyncio.sleep(0)
    assert "endpoint status init failed" in caplog.text
