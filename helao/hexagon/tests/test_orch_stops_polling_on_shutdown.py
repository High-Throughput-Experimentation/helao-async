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
from helao.hexagon.app.ingestion import HexHealthMonitor
from helao.hexagon.app.orch_host import OrchHost


class _Probe(OrchHost):
    """An OrchHost whose construction is skipped; only shutdown is exercised."""

    def __init__(self):  # noqa: D107  (deliberately not building a server)
        self.exports = 0
        self.sequence_dq = ["one queued sequence"]
        self.experiment_dq = []
        self.action_dq = []
        self._hex_health = HexHealthMonitor(None, None, None)
        self.status_subscriber = None
        self.driver_monitor = None
        self.heartbeat_monitor = None

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
    probe._hex_health._task = asyncio.create_task(_never())

    await probe.shutdown()
    await asyncio.sleep(0)

    # The heartbeat is the loop that POSTs /get_status; it must be done before
    # the action servers start disconnecting their drivers.
    assert probe.heartbeat_monitor.cancelled()
    assert probe.driver_monitor.cancelled()
    # the health monitor's own probe loop must stop too (it has close(), not stop())
    assert probe._hex_health._task.cancelled()
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


@pytest.mark.asyncio
async def test_shutdown_exports_a_parked_head_when_every_deque_is_empty(
    monkeypatch, tmp_path
):
    """The last action of an experiment waiting on its start condition leaves all
    three deques empty; the head is then the only thing a restore could recover."""
    import pickle
    from types import SimpleNamespace

    from helao.hexagon.adapters.shared.state_persistence import QueuePckStore
    from helao.hexagon.app.orch_persist import QueuePersister
    from helao.hexagon.app.wiring import PortWiring

    async def _host_shutdown(self):
        return {}

    monkeypatch.setattr(ActionHost, "shutdown", _host_shutdown, raising=True)
    (tmp_path / "STATES").mkdir()
    head = "the parked head action"

    class _Exporting(_Probe):
        def export_queues(self, timestamp_pck=False):
            self.exports += 1
            fields = dict.fromkeys(
                (
                    "active_experiment",
                    "last_experiment",
                    "active_sequence",
                    "last_sequence",
                    "active_seq_exp_counter",
                    "last_action_uuid",
                    "last_dispatched_action_uuid",
                    "globalstatusmodel",
                    "active_run_id",
                )
            )
            orch = SimpleNamespace(
                world_cfg={"root": str(tmp_path)},
                hexagon_wiring=PortWiring(
                    state_persistence=QueuePckStore(str(tmp_path))
                ),
                sequence_dq=self.sequence_dq,
                experiment_dq=self.experiment_dq,
                action_dq=self.action_dq,
                parked_head_action=self.parked_head_action,
                action_history={},
                experiment_history={},
                sequence_history={},
                **fields,
            )
            return QueuePersister(orch).export_queues(timestamp_pck)

    probe = _Exporting()
    probe.sequence_dq = []
    probe.parked_head_action = head  # type: ignore[assignment]
    await probe.orch_shutdown()

    assert probe.exports == 1
    with open(tmp_path / "STATES" / "queues.pck", "rb") as f:
        assert pickle.load(f)["act"] == [head]
