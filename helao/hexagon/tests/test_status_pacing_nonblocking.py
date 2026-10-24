"""C4a: the per-client status pacing sleep must not block the event loop.

``log_status_task`` paces its sends to each subscriber by 0.3 s. That used to be
``time.sleep``, which froze every coroutine on the server (action dispatch,
websockets, other endpoints) for 0.3 s per client per status. The pacing is kept,
as ``await asyncio.sleep``.
"""

import asyncio
import tempfile
from typing import Any

import pytest

from helao.core.error import ErrorCodes
from helao.helpers.premodels import Action


def _host():
    """An ActionHost against an injected config and stubbed ports."""
    from helao.hexagon.app.action_host import ActionHost
    from helao.hexagon.app.wiring import PortWiring

    cfg = {
        "root": tempfile.mkdtemp(prefix="helao_pacing_test_"),
        "servers": {"SIM": {"host": "127.0.0.1", "port": 8002, "params": {}}},
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
    return ActionHost(
        server_key="SIM",
        server_title="SIM",
        description="status pacing test",
        version=1.0,
        wiring=wiring,
        helao_cfg=cfg,
    )


def _status():
    act = Action(action_name="act_a")
    act.action_server.server_name = "SIM"
    act.init_act()
    return act.get_act()


async def _run(clients):
    """Send one status to ``clients``; return (send times, largest loop gap)."""
    host = _host()
    loop = asyncio.get_running_loop()
    sent: list = []

    async def _send(**kwargs):
        sent.append(loop.time())
        return {"ok": 1}, ErrorCodes.none

    host.send_statuspackage = _send  # type: ignore[method-assign]
    host.status_clients = set(clients)
    worker = asyncio.create_task(host.log_status_task())
    gaps: list = []
    stop = asyncio.Event()

    async def _ticker():
        last = loop.time()
        while not stop.is_set():
            await asyncio.sleep(0.01)
            now = loop.time()
            gaps.append(now - last)
            last = now

    ticker = asyncio.create_task(_ticker())
    try:
        await asyncio.sleep(0.05)  # let the worker subscribe before the put
        await host.status_q.put(_status())
        await asyncio.sleep(0.5)  # covers the whole pacing window
    finally:
        stop.set()
        await ticker
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
    return sent, max(gaps)


@pytest.mark.asyncio
async def test_pacing_does_not_block_the_loop():
    sent, worst_gap = await _run({("ORCH", "127.0.0.1", 1)})

    assert len(sent) == 1
    # a blocking sleep leaves the loop dark for at least 0.29 s
    assert worst_gap < 0.15, worst_gap


@pytest.mark.asyncio
async def test_pacing_is_preserved_between_clients():
    sent, _ = await _run({("ORCH", "127.0.0.1", 1), ("ORCH2", "127.0.0.1", 2)})

    assert len(sent) == 2
    assert sent[1] - sent[0] >= 0.29, sent
