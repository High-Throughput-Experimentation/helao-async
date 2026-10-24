"""Gamry connects once, at host startup, and a raising connect keeps the server up.

``GamryDriver.__init__`` no longer connects (so a host with ``driver_classes=
[GamryDriver]`` starts on Linux, where ``comtypes`` is absent), and
``GamryComAdapter.connect()`` connects the wrapped driver itself. A raising startup
connect is logged at ERROR and alerted; the server still answers.
"""

import logging
import tempfile
from typing import Any

from fastapi.testclient import TestClient

from helao.deploy.hte.drivers.pstat.gamry.driver import GamryDriver
from helao.hexagon.adapters.native.gamry_com import GamryComAdapter
from helao.hexagon.tests.hosted_server import start_with_raising_connect


def test_gamry_server2_stays_up_after_a_raising_connect(monkeypatch, tmp_path, caplog):
    out = start_with_raising_connect(
        monkeypatch,
        tmp_path,
        caplog,
        module="gamry_server2",
        prefix="eche10",
        server_key="PSTAT",
        driver_class=GamryComAdapter,
        ready=lambda app: False,  # dyn_endpoints parks on `ready`; wait out the window
        wait_s=1.5,
        probe=lambda app: app.endpoint_mgr._init_task.done(),
    )
    assert len(out.startup_errors) == 1
    assert out.get_status_code == 200
    # parked on `ready`: no action routes, and the endpoint-status init is pending
    assert not any(p.endswith("/run_LSV") for p in out.route_paths if p)
    assert out.probe is False


def test_gamry_driver_host_starts_without_comtypes(caplog):
    """The shape a private deployment uses: the driver hosted directly.

    Before this increment the constructor imported ``comtypes`` and the host failed
    at construction. Now only ``connect()`` does, which the host catches.
    """
    from helao.deploy.hte.servers.action.gamry_server2 import gamry_dyn_endpoints
    from helao.hexagon.app import action_host
    from helao.hexagon.app.action_host import ActionHost
    from helao.hexagon.app.wiring import PortWiring

    class _Stub:
        def meta_writer_for(self, base):
            return object()

        def __getattr__(self, name):
            raise AssertionError(f"port member {name!r} used during construction")

    stub: Any = _Stub()
    wiring = PortWiring(
        config=stub,
        logging=stub,
        clock=stub,
        transport=stub,
        state_persistence=stub,
        health=stub,
        artifact_store=stub,
    )
    host = ActionHost(
        server_key="PSTAT",
        server_title="PSTAT",
        description="gamry host test",
        version=1.0,
        driver_classes=[GamryDriver],
        dyn_endpoints=gamry_dyn_endpoints,
        wiring=wiring,
        helao_cfg={
            "root": tempfile.mkdtemp(prefix="helao_gamry_host_"),
            "servers": {"PSTAT": {"host": "127.0.0.1", "port": 8763, "params": {}}},
        },
    )
    lg = action_host.LOGGER
    old_level = lg.level
    lg.setLevel(logging.DEBUG)
    lg.addHandler(caplog.handler)
    try:
        with TestClient(host) as client:
            status = client.post("/get_status")
    finally:
        lg.removeHandler(caplog.handler)
        lg.setLevel(old_level)
    errors = [
        r
        for r in caplog.records
        if "GamryDriver.connect() at startup raised" in r.getMessage()
        and r.levelno == logging.ERROR
    ]
    assert len(errors) == 1 and errors[0].exc_info
    assert status.status_code == 200
