"""The orchestrator must stop its own loops when /shutdown is POSTed.

``POST /shutdown`` reaches ``ActionHost.shutdown``. The orchestrator's
monitors -- the heartbeat that POSTs /get_status at every action server --
were cancelled only from the lifespan shutdown *event*, which uvicorn runs
after its graceful wait. So through the whole teardown the orchestrator kept
polling action servers that were already shutting down, and each failed poll
cost a 30 s retry sleep inside ``async_private_dispatcher``.

The launcher already sends /shutdown to orchestrators before action servers
(``launch.py``'s ``SHUTDOWN_POST_ORDER``) precisely so this can stop cleanly.
The orchestrator simply was not using its turn.

Both entry points now call ``orch_shutdown``, so it has to be idempotent: a
second run would export a second queue file from deques the first already
exported.
"""

import asyncio

import pytest

from helao.hexagon.app.action_host import ActionHost
from helao.hexagon.app.orch_host import OrchHost


class _Probe(OrchHost):
    """An OrchHost whose construction is skipped; only shutdown is exercised."""

    def __init__(self):  # noqa: D107  (deliberately not building a server)
        self.exports = 0
        self.stopped_health = 0
        self.sequence_dq = ["one queued sequence"]
        self.experiment_dq = []
        self.action_dq = []
        self._hex_health = self
        self.status_subscriber = None
        self.globstat_broadcaster = None
        self.driver_monitor = None
        self.heartbeat_monitor = None

    def stop(self):
        self.stopped_health += 1

    def export_queues(self, timestamp_pck=False):
        self.exports += 1
        return "queues.pck"


async def _never():
    await asyncio.sleep(3600)


@pytest.mark.asyncio
async def test_shutdown_cancels_the_monitors_before_the_host_shuts_down(monkeypatch):
    order = []

    async def _host_shutdown(self):
        order.append("host")
        return {}

    monkeypatch.setattr(ActionHost, "shutdown", _host_shutdown, raising=True)

    probe = _Probe()
    probe.heartbeat_monitor = asyncio.create_task(_never())
    probe.driver_monitor = asyncio.create_task(_never())

    await probe.shutdown()
    await asyncio.sleep(0)

    # The heartbeat is the loop that POSTs /get_status; it must be done before
    # the action servers start disconnecting their drivers.
    assert probe.heartbeat_monitor.cancelled()
    assert probe.driver_monitor.cancelled()
    assert order == ["host"], "the host's own shutdown must still run"


@pytest.mark.asyncio
async def test_orch_shutdown_exports_the_queues_once(monkeypatch):
    async def _host_shutdown(self):
        return {}

    monkeypatch.setattr(ActionHost, "shutdown", _host_shutdown, raising=True)

    probe = _Probe()
    await probe.shutdown()  # POST /shutdown
    await probe.orch_shutdown()  # the lifespan event, right behind it

    assert probe.exports == 1, (
        "a second export writes a second queue file from deques the first "
        "one already exported"
    )
