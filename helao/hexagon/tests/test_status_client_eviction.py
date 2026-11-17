"""A subscriber that fails a whole retry round is evicted; the orchestrator never is.

A dead runner that never detached used to stay in ``status_clients`` for good and
stall the serial fan-out for every later subscriber (5 retries per status).
"""

import tempfile
from typing import Any

import pytest

from helao.core.error import ErrorCodes
from helao.helpers.premodels import Action

ORCH = ("ORCH", "127.0.0.1", 9)
DEAD = ("R1", "127.0.0.1", 1)
LIVE = ("R2", "127.0.0.1", 2)


def _host():
    from helao.hexagon.app.action_host import ActionHost
    from helao.hexagon.app.wiring import PortWiring

    cfg = {
        "root": tempfile.mkdtemp(prefix="helao_evict_test_"),
        "servers": {
            "SIM": {"host": "127.0.0.1", "port": 8002, "params": {}},
            "ORCH": {
                "host": "127.0.0.1",
                "port": 9,
                "group": "orchestrator",
                "fast": "async_orch2",
            },
        },
    }

    class _Stub:
        def meta_writer_for(self, base):
            return object()

        def __getattr__(self, name):
            raise AssertionError(f"port member {name!r} used during construction")

    stub: Any = _Stub()
    wiring = PortWiring(
        config=stub,
        logging=stub,
        clock=stub,
        state_persistence=stub,
        health=stub,
        artifact_store=stub,
    )
    host = ActionHost(
        server_key="SIM",
        server_title="SIM",
        description="eviction test",
        version=1.0,
        wiring=wiring,
        helao_cfg=cfg,
    )
    assert (host.orch_key, host.orch_host, host.orch_port) == ORCH
    return host


def _send_that_fails(*dead):
    async def _send(**kw):
        key = (kw["client_servkey"], kw["client_host"], kw["client_port"])
        if key in dead:
            return None, ErrorCodes.unspecified
        return {"ok": 1}, ErrorCodes.none

    return _send


async def _one_status(host):
    import asyncio

    act = Action(action_name="act_a")
    act.action_server.server_name = "SIM"
    act.init_act()
    worker = asyncio.create_task(host.log_status_task(retry_limit=2))
    try:
        await asyncio.sleep(0.05)
        await host.status_q.put(act.get_act())
        await asyncio.sleep(1.0)
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.asyncio
async def test_log_status_task_evicts_dead_subscriber_and_keeps_orch():
    host = _host()
    host.send_statuspackage = _send_that_fails(DEAD, ORCH)  # type: ignore[method-assign]
    host.status_clients = {DEAD, LIVE, ORCH}
    await _one_status(host)
    assert host.status_clients == {LIVE, ORCH}


@pytest.mark.asyncio
async def test_regular_status_task_evicts_dead_subscriber_and_keeps_orch():
    import asyncio

    host = _host()
    host.send_statuspackage = _send_that_fails(DEAD, ORCH)  # type: ignore[method-assign]
    host.status_clients = {DEAD, LIVE, ORCH}
    worker = asyncio.create_task(host.regular_status_task(delay=5, retry_limit=2))
    try:
        await asyncio.sleep(0.3)
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
    assert host.status_clients == {LIVE, ORCH}


def test_orchestrator_spared_by_key_whatever_host_spelling():
    host = _host()
    orch_alias = ("ORCH", "localhost", "9")
    host.send_statuspackage = _send_that_fails(orch_alias)  # type: ignore[method-assign]
    host.status_clients = {orch_alias}
    host._evict_dead_client(orch_alias)
    assert host.status_clients == {orch_alias}
