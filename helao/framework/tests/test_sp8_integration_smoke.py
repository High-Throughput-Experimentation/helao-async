"""SP8 end-to-end smoke: the full status-push chain through the real BaseAPI.

Proves the SP8 critical path: a migrated test-deployment action server, driven
through its real FastAPI app, registers an orchestrator status client via
``attach_client`` and — when an action runs to completion — pushes a status
package to that client's ``update_status`` (the loop whose absence made
sequences hang). The dispatcher is mocked; everything else is the real wiring.
"""
import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from helao.framework.models.errors import ErrorCodes
from helao.framework.domain.run_models import RunAction
from helao.framework.models.machine import MachineModel


def _make_sim_app(tmp_path):
    from helao.deploy.test.servers.action.ws_simulator import makeApp
    from helao.framework.adapters.fs_storage import FsStorage

    app = makeApp("SIM")
    app.base.storage = FsStorage(str(tmp_path))
    return app


async def _run_startup(app) -> None:
    """Replicate the FastAPI startup hook (ASGITransport does not run lifespan)."""
    if getattr(app, "_drivers_deferred", False):
        app._instantiate_drivers()
        app._drivers_deferred = False
    app.base.init_endpoint_status(app)
    await app.base.start()


@pytest.mark.asyncio
async def test_status_pushed_to_attached_client_on_finish(tmp_path):
    app = _make_sim_app(tmp_path)
    await _run_startup(app)

    disp = AsyncMock(return_value=({}, ErrorCodes.none))
    with patch(
        "helao.framework.support.dispatcher.async_private_dispatcher", new=disp
    ):
        # orchestrator subscribes as a status client
        await app.base.attach_client("ORCH", "127.0.0.1", 8001)
        assert ("ORCH", "127.0.0.1", 8001) in app.base.status_clients

        action = RunAction(
            action_name="acquire_data",
            action_server=MachineModel(server_name="SIM"),
            action_params={"duration": 0.2, "acquisition_rate": 0.1},
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as client:
            resp = await client.post(
                "/SIM/acquire_data", json={"action": action.as_dict()}
            )
        assert resp.status_code == 200

        # let the action finish and the status-drain task push to the client
        for _ in range(50):
            await asyncio.sleep(0.1)
            update_calls = [
                c
                for c in disp.call_args_list
                if c.kwargs.get("private_action") == "update_status"
            ]
            if update_calls:
                break

    update_calls = [
        c
        for c in disp.call_args_list
        if c.kwargs.get("private_action") == "update_status"
    ]
    assert update_calls, "no update_status pushed to the attached orchestrator client"
    # the push targeted the registered orchestrator client
    assert any(c.kwargs.get("server_key") == "ORCH" for c in update_calls)
    # payload is the actionservermodel shape the orch's update_status parses
    assert any(
        "actionservermodel" in (c.kwargs.get("json_dict") or {}) for c in update_calls
    )


@pytest.mark.asyncio
async def test_detach_client_stops_pushes(tmp_path):
    app = _make_sim_app(tmp_path)
    await _run_startup(app)
    await app.base.attach_client("ORCH", "127.0.0.1", 8001)
    ok = app.base.detach_client("ORCH", "127.0.0.1", 8001)
    assert ok is True
    assert ("ORCH", "127.0.0.1", 8001) not in app.base.status_clients
