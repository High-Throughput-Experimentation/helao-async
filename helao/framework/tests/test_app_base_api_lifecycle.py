"""Driver background-task lifecycle tests for ``app/base_api.py`` (SP8 WS-C).

Covers the startup/shutdown driver lifecycle that fixes the orphaned-poll-loop
bug: ``test``-deployment drivers (e.g. ``WsSim``) start an asyncio task in
``__init__`` via ``asyncio.get_event_loop().create_task(...)``. Instantiating
drivers in ``BaseAPI.__init__`` (no running loop) orphans that task on a dead
loop. The fix defers driver instantiation to the FastAPI ``startup`` event (loop
running) so the driver's own task binds to the live loop.

* **T-self-populate** — drive the migrated ``ws_simulator`` through an ASGI
  client lifespan, then POST ``acquire_data`` with a full action body and assert
  the live buffer populated and an ``.hlo`` was written **without** manually
  seeding ``put_lbuf`` (proves the ``WsSim`` poll loop now runs).
* **T-shutdown** — the shutdown hook calls each driver's ``shutdown`` /
  ``async_shutdown`` (verified with a fake driver class recording calls).
* **T-deferred** — drivers do not exist until the startup hook fires.
"""
import asyncio
import uuid as _uuid

import httpx
import pytest

from helao.framework.app.base_api import BaseAPI
from helao.framework.tests.conftest import asgi_lifespan


# ---------------------------------------------------------------------------
# T-self-populate — WsSim poll loop runs under the ASGI lifespan
# ---------------------------------------------------------------------------


def _action_body(action_uuid: str) -> dict:
    """Full action body mirroring what the orch POSTs (no manual buffer seed)."""
    file_conn = str(_uuid.uuid4())
    return {
        "action": {
            "action_name": "acquire_data",
            "action_uuid": action_uuid,
            "action_timestamp": "2026-06-23T00:00:00",
            "sequence_timestamp": "2026-06-23T00:00:00",
            "experiment_timestamp": "2026-06-23T00:00:00",
            "sequence_name": "seq",
            "experiment_name": "exp",
            "action_output_dir": "26.25/0623/0__0__SIM__acquire_data",
            "save_act": True,
            "save_data": True,
            "file_conn_keys": [file_conn],
            "action_params": {"duration": 0.2, "acquisition_rate": 0.05},
        }
    }


@pytest.mark.asyncio
async def test_ws_simulator_self_populates_live_buffer():
    """The WsSim poll loop self-populates the live buffer under the lifespan.

    No ``put_lbuf`` seeding: if the driver's poll loop binds to the live loop
    (the fix), ``sim_dict`` appears in the live buffer and the executor writes a
    real ``.hlo``.
    """
    from pathlib import Path

    from helao.deploy.test.servers.action.ws_simulator import makeApp

    app = makeApp("SIM")
    save_root = Path(app.state.save_root)

    transport = httpx.ASGITransport(app=app)
    async with asgi_lifespan(app):
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            # startup fired -> drivers exist + poll loop running on this loop
            assert app.driver is not None, "driver not built by startup hook"
            # let the 10 Hz poll loop populate the live buffer
            await asyncio.wait_for(
                _wait_for_lbuf(app.base, "sim_dict"), timeout=2.0
            )
            assert "sim_dict" in app.base.live_buffer

            resp = await client.post(
                "/SIM/acquire_data", json=_action_body(str(_uuid.uuid4()))
            )
            assert resp.status_code == 200, resp.text
            await asyncio.sleep(0.5)  # let the bounded-duration executor finish

    hlo_files = list(save_root.rglob("*.hlo"))
    assert hlo_files, "ws_simulator wrote no .hlo without manual put_lbuf seeding"


async def _wait_for_lbuf(base, key):
    while key not in base.live_buffer:
        await asyncio.sleep(0.02)


# ---------------------------------------------------------------------------
# T-deferred — drivers are built by the startup hook, not __init__
# ---------------------------------------------------------------------------


class RecordingDriver:
    """Bare-helper driver recording construction + shutdown calls."""

    instances: list = []

    def __init__(self, base):
        self.base = base
        self.shutdown_called = False
        self.async_shutdown_called = False
        RecordingDriver.instances.append(self)

    async def async_shutdown(self):
        self.async_shutdown_called = True

    def shutdown(self):
        self.shutdown_called = True


class SyncOnlyDriver:
    """Bare-helper driver with only a synchronous ``shutdown``."""

    def __init__(self, base):
        self.base = base
        self.shutdown_called = False

    def shutdown(self):
        self.shutdown_called = True


@pytest.mark.asyncio
async def test_drivers_deferred_to_startup(tmp_path):
    RecordingDriver.instances = []
    app = BaseAPI(
        server_key="SIM",
        driver_classes=[RecordingDriver],
        save_root=str(tmp_path),
    )
    # before the lifespan, no driver yet (deferred to startup)
    assert app.driver is None
    assert app.drivers == tuple()
    assert RecordingDriver.instances == []

    async with asgi_lifespan(app):
        assert isinstance(app.driver, RecordingDriver)
        assert app.drivers[0] is app.driver
        assert app.driver.base is app.base


# ---------------------------------------------------------------------------
# T-shutdown — shutdown hook calls async_shutdown (preferred) else shutdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shutdown_hook_prefers_async_shutdown(tmp_path):
    RecordingDriver.instances = []
    app = BaseAPI(
        server_key="SIM",
        driver_classes=[RecordingDriver],
        save_root=str(tmp_path),
    )
    async with asgi_lifespan(app):
        driver = app.driver
    # exiting the context fired the shutdown event
    assert driver.async_shutdown_called is True
    assert driver.shutdown_called is False


@pytest.mark.asyncio
async def test_shutdown_hook_falls_back_to_sync_shutdown(tmp_path):
    app = BaseAPI(
        server_key="SIM",
        driver_classes=[SyncOnlyDriver],
        save_root=str(tmp_path),
    )
    async with asgi_lifespan(app):
        driver = app.driver
    assert driver.shutdown_called is True
