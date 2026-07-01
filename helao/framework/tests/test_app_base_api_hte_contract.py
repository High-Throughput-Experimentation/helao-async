"""Framework BaseAPI contract used by real hte action servers.

These three gaps surfaced at the first live multi-driver station launch
(eche10, 2026-07-01); the ``test``-deployment sims (bare helpers) never
exercised them:

- ``dyn_endpoints`` may be ``async def`` (galil/gamry/sm303) and MUST be
  awaited, else the dynamic action routes are never registered.
- ``app.server_params`` must exist on the BaseAPI app (pal_server reads it).
- ``BaseAPI(poller_class=...)`` must be accepted and wire a ``DriverPoller``
  onto the first ``HelaoDriver`` (kinesis_server).
"""
from fastapi.testclient import TestClient

from helao.framework.app.base_api import BaseAPI
from helao.framework.ports.driver import HelaoDriver, DriverResponse


class Drv(HelaoDriver):
    def connect(self):
        return DriverResponse()

    def get_status(self):
        return DriverResponse()

    def stop(self):
        return DriverResponse()

    def reset(self):
        return DriverResponse()

    def disconnect(self):
        return DriverResponse()


class _Poller:
    """Minimal DriverPoller stand-in: records what the app wired it with."""

    def __init__(self, driver, polling_time):
        self.driver = driver
        self.polling_time = polling_time
        self._base_hook = None


def test_baseapi_exposes_server_params(tmp_path):
    app = BaseAPI("srv", save_root=str(tmp_path))
    assert hasattr(app, "server_params"), "BaseAPI app must expose server_params"
    assert app.server_params == {}
    # app.helao_cfg (whole world config) is read by mfc_server off the app.
    assert hasattr(app, "helao_cfg"), "BaseAPI app must expose helao_cfg"
    assert app.helao_cfg == app.base.helao_cfg


def test_baseapi_accepts_and_wires_poller_class(tmp_path):
    app = BaseAPI(
        "srv", save_root=str(tmp_path),
        driver_classes=[Drv], poller_class=_Poller,
    )
    with TestClient(app):  # triggers startup -> _instantiate_drivers
        assert isinstance(app.poller, _Poller)
        assert app.poller.driver is app.driver
        assert app.poller._base_hook is app.base


def test_async_dyn_endpoints_are_awaited(tmp_path):
    marker = {}

    async def dyn(app):
        marker["ran"] = True

        @app.get("/srv/dynping")
        def dynping():
            return {"ok": True}

    app = BaseAPI("srv", save_root=str(tmp_path), dyn_endpoints=dyn)
    with TestClient(app) as client:
        assert marker.get("ran") is True, "async dyn_endpoints body never executed"
        assert client.get("/srv/dynping").status_code == 200


def test_sync_dyn_endpoints_still_registered(tmp_path):
    def dyn(app):
        @app.get("/srv/syncping")
        def syncping():
            return {"ok": True}

    app = BaseAPI("srv", save_root=str(tmp_path), dyn_endpoints=dyn)
    with TestClient(app) as client:
        assert client.get("/srv/syncping").status_code == 200
