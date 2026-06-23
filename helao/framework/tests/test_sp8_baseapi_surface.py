"""SP8 WS-B/WS-C: action-server FastAPI surface + lifecycle.

Covers the production surface added on top of WS-A:

* the ``/ws_status`` websocket relay forwards a status emission to a client;
* ``/endpoints`` returns the route descriptor list;
* ``/get_lbuf`` returns a buffered value;
* ``/stop_executor`` calls ``stop_action_task`` on the registered session;
* HEAD mirrors of POST routes return 200;
* dual-convention driver instantiation: a ``HelaoDriver`` subclass gets
  ``config=server_params``, a bare class gets the ``FrameworkBase``;
* driver instantiation deferred to startup when eager construction touches a
  not-yet-running event loop.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from helao.framework.app.server_api import BaseAPI, _ws_relay, _build_fast_urls
from helao.framework.app.base_api import FrameworkBase
from helao.framework.ports.driver import (
    DriverResponse,
    DriverResponseType,
    DriverStatus,
    HelaoDriver,
)
from helao.framework.ports.eventsink import STATUS_CHANNEL


# --- dual-convention driver instantiation (WS-C task 5) -----------------------


class _BareDriver:
    """Bare helper driver — receives the FrameworkBase instance."""

    def __init__(self, base: FrameworkBase):
        self.base = base


class _RealDriver(HelaoDriver):
    """Real HelaoDriver subclass — receives ``config=server_params``."""

    def connect(self):
        return DriverResponse(response=DriverResponseType.success, status=DriverStatus.ok)

    def get_status(self):
        return DriverResponse(response=DriverResponseType.success, status=DriverStatus.ok)

    def stop(self):
        return DriverResponse(response=DriverResponseType.success, status=DriverStatus.ok)

    def reset(self):
        return DriverResponse(response=DriverResponseType.success, status=DriverStatus.ok)

    def disconnect(self):
        return DriverResponse(response=DriverResponseType.success, status=DriverStatus.ok)


def test_bare_driver_gets_base(tmp_path):
    app = BaseAPI("SRV", driver_classes=[_BareDriver], save_root=str(tmp_path))
    assert isinstance(app.driver, _BareDriver)
    assert app.driver.base is app.base


def test_helao_driver_gets_config(tmp_path):
    app = BaseAPI("SRV", driver_classes=[_RealDriver], save_root=str(tmp_path))
    assert isinstance(app.driver, _RealDriver)
    # HelaoDriver records its config dict; bare drivers never touch ``config``.
    assert isinstance(app.driver.config, dict)
    assert app.driver.config is app.server_params


def test_loop_touching_driver_deferred_then_built_at_startup(tmp_path):
    class _LoopDriver:
        """Bare driver that grabs the running loop at construction (like WsSim)."""

        def __init__(self, base: FrameworkBase):
            self.base = base
            self.loop = asyncio.get_running_loop()

    app = BaseAPI("SRV", driver_classes=[_LoopDriver], save_root=str(tmp_path))
    # eager construction raised (no running loop) -> deferred, driver not built yet
    assert app.driver is None
    assert app._drivers_deferred is True
    # the startup hook (fired by TestClient) builds it inside the loop
    with TestClient(app):
        assert isinstance(app.driver, _LoopDriver)
        assert app._drivers_deferred is False


# --- /endpoints ---------------------------------------------------------------


def test_endpoints_returns_routes(tmp_path):
    app = BaseAPI("SRV", save_root=str(tmp_path))

    @app.post("/SRV/do_thing", tags=["action"])
    async def do_thing():
        return await app.base.setup_and_contain_action()

    with TestClient(app) as client:
        resp = client.post("/endpoints")
    assert resp.status_code == 200
    urls = resp.json()
    names = {u["name"] for u in urls}
    assert "do_thing" in names
    assert "get_config" in names


def test_build_fast_urls_shape(tmp_path):
    app = BaseAPI("SRV", save_root=str(tmp_path))
    urls = _build_fast_urls(app)
    assert all("path" in u and "name" in u and "params" in u for u in urls)


# --- /get_lbuf ----------------------------------------------------------------


def test_get_lbuf_returns_buffered_value(tmp_path):
    app = BaseAPI("SRV", save_root=str(tmp_path))
    app.base.put_lbuf_nowait({"temp": 21.5})
    with TestClient(app) as client:
        resp = client.post("/get_lbuf", params={"live_key": "temp"})
    assert resp.status_code == 200
    value, _ts = resp.json()
    assert value == 21.5


# --- /stop_executor -----------------------------------------------------------


def test_stop_executor_calls_stop_action_task(tmp_path):
    app = BaseAPI("SRV", save_root=str(tmp_path))

    class _FakeSession:
        def __init__(self):
            self.stopped = False

        def stop_action_task(self):
            self.stopped = True

    session = _FakeSession()
    app.base.executors["exec-1"] = session

    with TestClient(app) as client:
        resp = client.post("/stop_executor", params={"executor_id": "exec-1"})
        miss = client.post("/stop_executor", params={"executor_id": "nope"})

    assert resp.status_code == 200
    assert resp.json() == {"signal_stop": True}
    assert session.stopped is True
    assert miss.json() == {"signal_stop": False}


# --- /list_executors + /get_config --------------------------------------------


def test_list_executors_and_get_config(tmp_path):
    app = BaseAPI("SRV", save_root=str(tmp_path))
    app.base.executors["exec-1"] = object()
    with TestClient(app) as client:
        execs = client.post("/list_executors").json()
        cfg = client.post("/get_config")
    assert "exec-1" in execs
    assert cfg.status_code == 200
    assert isinstance(cfg.json(), dict)


# --- HEAD mirror --------------------------------------------------------------


def test_head_mirror_returns_200(tmp_path):
    app = BaseAPI("SRV", save_root=str(tmp_path))
    with TestClient(app) as client:
        # /endpoints is a POST route; the startup hook adds a HEAD mirror.
        resp = client.head("/endpoints")
    assert resp.status_code == 200


# --- /ws_status relay ---------------------------------------------------------


def test_ws_status_relay_forwards_status_emission(tmp_path):
    """A status emission on the eventsink is forwarded to a connected client.

    Drives the emission through the app's own portal thread (the loop the
    websocket handler runs on) via the route's POST surface: emitting from a
    private endpoint that runs on the same loop guarantees the relay sees it.
    """
    app = BaseAPI("SRV", save_root=str(tmp_path))
    payload = {"action_name": "run_dummy", "action_uuid": "abc"}

    @app.post("/emit_test", tags=["private"])
    async def emit_test():
        await app.base.eventsink.emit_status(payload)
        return True

    with TestClient(app) as client:
        with client.websocket_connect("/ws_status") as ws:
            # the relay subscribed during connect; now emit on the app loop.
            assert client.post("/emit_test").json() is True
            got = ws.receive_json()
    assert got == payload


def test_ws_relay_helper_forwards_matching_channel():
    """Unit-level: the relay helper forwards only payloads on its channel."""
    from helao.framework.adapters.queue_eventsink import QueueEventSink

    class _FakeBase:
        def __init__(self):
            self.eventsink = QueueEventSink()

    sent = []

    class _FakeWS:
        async def accept(self):
            pass

        async def send_json(self, data):
            sent.append(data)
            raise RuntimeError("stop relay")  # end the loop after one send

        @property
        def client(self):
            return ("127.0.0.1", 1)

    base = _FakeBase()

    async def _go():
        relay = asyncio.create_task(
            _ws_relay(base, _FakeWS(), STATUS_CHANNEL, "status")
        )
        await asyncio.sleep(0)
        await base.eventsink.emit("data", {"ignored": True})
        await base.eventsink.emit_status({"kept": True})
        await relay

    asyncio.run(_go())
    assert sent == [{"kept": True}]
