"""SP8 WS-A: action-server -> orchestrator status-push loop.

Covers the restored ``attach_client`` -> emit -> ``update_status`` pipeline on
:class:`FrameworkBase`:

* ``init_endpoint_status`` builds an :class:`EndpointModel` per action route;
* ``attach_client`` registers a client and delivers the current snapshot;
* ``detach_client`` removes it;
* a blocking status emitted through the event sink is forwarded to every
  registered client by POSTing an ``ActionModel``-shaped ``actionservermodel``
  payload to its ``update_status`` (dispatcher patched);
* a non-blocking status is routed to ``update_nonblocking`` instead.
"""
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from fastapi import FastAPI

from helao.framework.models.errors import ErrorCodes
from helao.framework.models.hlostatus import HloStatus
from helao.framework.app.base_api import FrameworkBase
from helao.framework.adapters.queue_eventsink import QueueEventSink
from helao.framework.adapters.fakes.clock import FakeClock
from helao.framework.adapters.fakes.storage import FakeStorage
from helao.framework.adapters.fakes.transport import FakeTransport

FIXED_NOW = datetime(2026, 6, 23, 9, 0, 0)
ACT_UUID = UUID("00000000-0000-0000-0000-0000000000aa")

# dispatcher patch target: the module the symbol is *imported into* at call time.
DISPATCH = "helao.framework.support.dispatcher.async_private_dispatcher"


def _base(**kwargs) -> FrameworkBase:
    return FrameworkBase(
        server_key="srv",
        storage=FakeStorage(),
        eventsink=QueueEventSink(),
        clock=FakeClock(),
        transport=FakeTransport(),
        **kwargs,
    )


def _status_payload(nonblocking: bool = False) -> dict:
    """An ``ActionModel``-shaped status dict for action ``ACT_UUID`` on ``srv``."""
    return {
        "action_name": "run_dummy",
        "action_uuid": str(ACT_UUID),
        "action_timestamp": FIXED_NOW.isoformat(),
        "action_status": [HloStatus.finished.value],
        "action_server": {"server_name": "srv"},
        "nonblocking": nonblocking,
    }


# --- init_endpoint_status -----------------------------------------------------


def test_init_endpoint_status_builds_endpoints_from_routes():
    base = _base()
    app = FastAPI()

    @app.post("/srv/run_dummy", tags=["action"])
    def run_dummy():
        return {}

    @app.post("/srv/run_other", tags=["action"])
    def run_other():
        return {}

    @app.post("/other_server/ignored")
    def ignored():
        return {}

    base.init_endpoint_status(app)

    names = set(base.actionservermodel.endpoints.keys())
    assert "run_dummy" in names
    assert "run_other" in names
    assert "ignored" not in names  # path doesn't start with /srv


# --- attach_client / detach_client --------------------------------------------


def test_attach_client_registers_and_returns_snapshot():
    base = _base()

    async def _go():
        with patch(DISPATCH, new=AsyncMock(return_value=({"ok": True}, ErrorCodes.none))) as disp:
            ok = await base.attach_client("orch", "127.0.0.1", 8001)
        return ok, disp

    ok, disp = asyncio.run(_go())
    assert ok is True
    assert ("orch", "127.0.0.1", 8001) in base.status_clients
    # the snapshot POST went to the client's update_status (action_name=None)
    disp.assert_awaited()
    kwargs = disp.await_args.kwargs
    assert kwargs["private_action"] == "update_status"
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8001
    assert "actionservermodel" in kwargs["json_dict"]


def test_detach_client_removes_registration():
    base = _base()
    base.status_clients.add(("orch", "127.0.0.1", 8001))
    assert base.detach_client("orch", "127.0.0.1", 8001) is True
    assert ("orch", "127.0.0.1", 8001) not in base.status_clients
    # detaching an unknown client returns False
    assert base.detach_client("nope", "x", 1) is False


# --- emit -> forward to client ------------------------------------------------


def test_emitted_status_is_forwarded_to_registered_client():
    base = _base()

    async def _go():
        with patch(
            DISPATCH, new=AsyncMock(return_value=({"ok": True}, ErrorCodes.none))
        ) as disp:
            await base.start()  # start the drain task
            await base.attach_client("orch", "127.0.0.1", 8001)
            disp.reset_mock()  # ignore the attach snapshot POST
            # emit a blocking status through the eventsink (as ActionSession does)
            await base.eventsink.emit_status(_status_payload())
            # let the drain task pick it up and push it
            for _ in range(50):
                await asyncio.sleep(0)
                if disp.await_count:
                    break
        return disp

    disp = asyncio.run(_go())
    disp.assert_awaited()
    kwargs = disp.await_args.kwargs
    assert kwargs["private_action"] == "update_status"
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8001
    asm = kwargs["json_dict"]["actionservermodel"]
    # ActionModel-shaped payload: the action shows up under its endpoint
    eps = asm["endpoints"]
    assert "run_dummy" in eps
    # finished action sorted into the nonactive (finished) bucket
    finished = eps["run_dummy"]["nonactive_dict"]
    assert any(str(ACT_UUID) in str(bucket) for bucket in finished.values())


def test_nonblocking_status_routes_to_update_nonblocking():
    base = _base()

    async def _go():
        with patch(
            DISPATCH,
            new=AsyncMock(return_value=({"success": True}, ErrorCodes.none)),
        ) as disp:
            await base.start()
            base.status_clients.add(("orch", "127.0.0.1", 8001))
            await base.eventsink.emit(
                "nonblocking_status", _status_payload(nonblocking=True)
            )
            for _ in range(50):
                await asyncio.sleep(0)
                if disp.await_count:
                    break
        return disp

    disp = asyncio.run(_go())
    disp.assert_awaited()
    kwargs = disp.await_args.kwargs
    assert kwargs["private_action"] == "update_nonblocking"
    assert "actionmodel" in kwargs["json_dict"]
    assert kwargs["json_dict"]["actionmodel"]["action_uuid"] == str(ACT_UUID)


def test_drain_task_started_lazily_not_at_init():
    # constructing the base must not require a running loop (Python 3.12 raises)
    base = _base()
    assert base._status_drain_task is None
