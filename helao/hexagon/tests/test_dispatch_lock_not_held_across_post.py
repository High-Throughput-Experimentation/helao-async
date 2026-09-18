"""The dispatch must not hold ``aiolock`` while the action's POST is open.

``/update_status`` takes the same lock. A blocking action holds its POST for
the whole action, so a lock wrapped around the dispatch call stops every
status package that server sends for that entire duration. Measured at eche10
on a 69 s move: MOTOR's ``active`` package for the move timed out at 60 s,
slept 30 s, and only landed at 10:28:34 -- after the action had already
finished at 10:28:10.

The split has a consequence the second test pins: ingestion can now fold this
action's status *while the dispatch is still in flight*, so the dispatch
response is no longer necessarily the freshest view of the action. For a short
action the FINISHED package can arrive first, and re-registering the action as
active from the stale response would strand it in ``active_dict`` -- the
packages that would have cleared it are already spent.
"""

import asyncio
from collections import deque
from datetime import datetime
from uuid import uuid4

import pytest

from helao.core.error import ErrorCodes
from helao.core.models.hlostatus import HloStatus
from helao.core.models.machine import MachineModel
from helao.core.models.server import (
    ActionServerModel,
    EndpointModel,
    GlobalStatusModel,
)
from helao.helpers.premodels import Action
from helao.hexagon.app.orch_dispatch import DispatchRunner

ORCH_M = MachineModel(server_name="ORCH", machine_name="testhost")
SIM_M = MachineModel(
    server_name="SIM", machine_name="testhost", hostname="127.0.0.1", port=8002
)


def _act(uuid, statuses):
    return Action(
        action_uuid=uuid,
        action_name="acquire",
        action_status=list(statuses),
        action_server=SIM_M,
        orchestrator=ORCH_M,
        action_timestamp=datetime.now(),
    )


class _DispatchOrch:
    """The call-time orch surface ``_dispatch_action_locked`` reaches into."""

    def __init__(self):
        self.aiolock = asyncio.Lock()
        self.globalstatusmodel = GlobalStatusModel(orchestrator=ORCH_M)
        self.globalstatusmodel.server_dict[("SIM", "testhost", 8002)] = (
            ActionServerModel(
                action_server=SIM_M,
                endpoints={"acquire": EndpointModel(endpoint_name="acquire")},
            )
        )
        self.world_cfg = {"servers": {"SIM": {"host": "127.0.0.1", "port": 8002}}}
        self.action_dq = deque()
        self.last_action_uuid = None
        self.last_dispatched_action_uuid = None
        self.current_stop_message = ""
        self.lbuf = []
        self.stopped = False

    def track_action_uuid(self, action_uuid):
        self.last_dispatched_action_uuid = action_uuid

    def put_lbuf_nowait(self, live_dict):
        self.lbuf.append(live_dict)

    async def stop(self):
        self.stopped = True


def _patch_dispatcher(monkeypatch, fn):
    # _dispatch_action_locked imports the name from helao.core.servers.orch
    # at call time, so that module's attribute is the seam.
    import helao.core.servers.orch as orch_mod

    monkeypatch.setattr(orch_mod, "async_action_dispatcher", fn, raising=True)


@pytest.mark.asyncio
async def test_update_status_can_take_the_lock_while_a_dispatch_is_in_flight(
    monkeypatch,
):
    orch = _DispatchOrch()
    uuid = uuid4()
    in_flight = asyncio.Event()

    async def slow_dispatch(world_cfg, A, **kwargs):
        in_flight.set()
        await asyncio.sleep(0.5)
        return _act(uuid, [HloStatus.active]).as_dict(), ErrorCodes.none

    _patch_dispatcher(monkeypatch, slow_dispatch)

    A = _act(uuid, [])
    A.nonblocking = True  # skip self-registration; the lock is what's under test
    task = asyncio.create_task(DispatchRunner(orch)._dispatch_action_locked(A))

    await asyncio.wait_for(in_flight.wait(), 1.0)
    # This is the assertion the station failure reduces to: with the lock held
    # across the POST it raises TimeoutError, which is a status package lost
    # for the action's whole duration.
    await asyncio.wait_for(orch.aiolock.acquire(), 0.2)
    orch.aiolock.release()

    error_code, result = await asyncio.wait_for(task, 2.0)
    assert error_code is None
    assert result is not None


@pytest.mark.asyncio
async def test_a_status_already_ingested_is_not_re_registered_as_active(monkeypatch):
    orch = _DispatchOrch()
    uuid = uuid4()

    async def dispatch_that_finishes_first(world_cfg, A, **kwargs):
        # Ingestion folds the FINISHED package while the POST is still open --
        # reachable only because the lock is no longer held across it.
        finished = _act(uuid, [HloStatus.finished])
        orch.globalstatusmodel.nonactive_dict[HloStatus.finished] = {uuid: finished}
        # The response still describes the action as it was at begin().
        return _act(uuid, [HloStatus.active]).as_dict(), ErrorCodes.none

    _patch_dispatcher(monkeypatch, dispatch_that_finishes_first)

    A = _act(uuid, [])
    A.nonblocking = False
    await DispatchRunner(orch)._dispatch_action_locked(A)

    assert uuid not in orch.globalstatusmodel.active_dict, (
        "a finished action was re-registered as active from the stale dispatch "
        "response; nothing clears it after that"
    )
