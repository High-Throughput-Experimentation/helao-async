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
import asyncio

from fastapi.testclient import TestClient

from helao.framework.app.base_api import BaseAPI, FrameworkBase, ActionContext
from helao.framework.ports.driver import HelaoDriver, DriverResponse
from helao.framework.adapters.fs_storage import FsStorage
from helao.framework.adapters.queue_eventsink import QueueEventSink
from helao.framework.adapters.ntp_clock import NtpClock
from helao.framework.adapters.fakes.transport import FakeTransport
from helao.framework.domain.run_models import RunAction
from helao.framework.models.file import HloHeaderModel


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


def _base(tmp_path):
    return FrameworkBase(
        server_key="PSTAT",
        storage=FsStorage(save_root=str(tmp_path)),
        eventsink=QueueEventSink(),
        clock=NtpClock(),
        transport=FakeTransport(),
    )


def test_setup_and_contain_accepts_legacy_kwargs_and_stamps(tmp_path):
    """setup_and_contain_action takes the legacy kwargs (action_abbr/hloheader/
    file_type/json_data_keys) and myinit stamps action identity when unset."""
    base = _base(tmp_path)
    # A direct/Swagger-style action: no timestamps, no output dir (as arrives
    # when dispatched outside the orchestrator, e.g. gamry run_OCV via Swagger).
    action = RunAction(action_name="run_OCV", save_act=True, save_data=True)
    assert action.action_timestamp is None

    async def _drive():
        return await base.setup_and_contain_action(
            ActionContext(action=action, endpoint_name="run_OCV"),
            json_data_keys=["t_s", "Ewe_V"],
            action_abbr="OCV",
            file_type="pstat_helao__file",
            hloheader=HloHeaderModel(column_headings=["t_s", "Ewe_V"]),
        )

    session = asyncio.run(_drive())
    # kwargs applied
    assert session.action.action_abbr == "OCV"
    # myinit stamped identity (would previously crash on None.strftime)
    assert session.action.action_timestamp is not None
    assert session.action.action_output_dir is not None
    # unparented -> promoted to a manual run
    assert session.action.manual_action is True
    # the -act.yml meta actually landed on disk
    assert list(tmp_path.rglob("*-act.yml")), "no *-act.yml written"


def test_sync_dyn_endpoints_still_registered(tmp_path):
    def dyn(app):
        @app.get("/srv/syncping")
        def syncping():
            return {"ok": True}

    app = BaseAPI("srv", save_root=str(tmp_path), dyn_endpoints=dyn)
    with TestClient(app) as client:
        assert client.get("/srv/syncping").status_code == 200
