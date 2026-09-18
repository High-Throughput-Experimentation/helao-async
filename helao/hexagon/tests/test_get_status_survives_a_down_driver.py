"""``/get_status`` must answer while the driver is disconnected.

At CTRL-x the orchestrator's heartbeat is still polling /get_status while the
action servers are running their shutdown hooks, so it reaches servers whose
driver has already disconnected. ``GamryComAdapter.get_status`` raises
``RuntimeError("GamryComAdapter is not connected")`` in that window, and the
route let it escape -- uvicorn turned it into a 500 with a **text/plain**
body, which meant an ASGI traceback on the action server, an undecodable
response at the orchestrator, and a 30 s retry sleep there for a poll whose
answer no longer mattered.

A driver that is not connected is a reportable state, so the route reports it.

The client is deliberately used *without* its context manager: that skips the
lifespan events, so no drivers are constructed and no background loops start.
The route is what is under test.
"""

import tempfile

import pytest
from fastapi.testclient import TestClient

from helao.core.drivers.helao_driver import (
    DriverResponse,
    DriverStatus,
    HelaoDriver,
)


class _DownDriver(HelaoDriver):
    """Raises the way a disconnected vendor adapter does."""

    def connect(self) -> DriverResponse:
        raise RuntimeError("driver is not connected")

    def get_status(self) -> DriverResponse:
        raise RuntimeError("driver is not connected")

    def stop(self) -> DriverResponse:
        raise RuntimeError("driver is not connected")

    def reset(self) -> DriverResponse:
        raise RuntimeError("driver is not connected")

    def disconnect(self) -> DriverResponse:
        raise RuntimeError("driver is not connected")


class _UpDriver(_DownDriver):
    def get_status(self) -> DriverResponse:  # type: ignore[override]
        return DriverResponse(status=DriverStatus.ok)


def _host():
    """An ActionHost against an injected config and stubbed ports."""
    from helao.hexagon.app.action_host import ActionHost
    from helao.hexagon.app.wiring import PortWiring

    cfg = {
        "root": tempfile.mkdtemp(prefix="helao_get_status_test_"),
        "servers": {"SIM": {"host": "127.0.0.1", "port": 8002, "params": {}}},
    }

    class _Stub:
        def meta_writer_for(self, base):
            return object()

        def __getattr__(self, name):
            raise AssertionError(f"port member {name!r} used during construction")

    wiring = PortWiring(
        config=_Stub(),
        logging=_Stub(),
        clock=_Stub(),
        transport=_Stub(),
        state_persistence=_Stub(),
        status=_Stub(),
        health=_Stub(),
        artifact_store=_Stub(),
        data_sink=_Stub(),
    )
    return ActionHost(
        server_key="SIM",
        server_title="SIM",
        description="get_status teardown test",
        version=1.0,
        wiring=wiring,
        helao_cfg=cfg,
    )


@pytest.fixture
def host():
    return _host()


def test_get_status_reports_unknown_instead_of_raising(host):
    host.driver = _DownDriver()
    host.poller = None
    resp = TestClient(host).post("/get_status")
    assert resp.status_code == 200, resp.text
    assert resp.json()["_driver_status"] == "unknown"


def test_a_healthy_driver_still_reports_its_own_status(host):
    host.driver = _UpDriver()
    host.poller = None
    resp = TestClient(host).post("/get_status")
    assert resp.status_code == 200, resp.text
    assert resp.json()["_driver_status"] == DriverStatus.ok
