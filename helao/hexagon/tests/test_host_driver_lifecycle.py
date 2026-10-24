"""Host order at startup: construct, ``_base_hook``, connect, poller, ``dyn_endpoints``.

The host owns driver connection. For a driver with ``connect_on_startup = True`` it
sets ``_base_hook``, calls ``connect()`` once, then builds the poller and runs
``dyn_endpoints``. A ``connect()`` that raises is logged at ERROR with the
traceback and alerted; the server still starts with the driver disconnected.
Constructor exceptions still stop startup.
"""

import logging
from typing import Any
import tempfile
import time

import pytest
from fastapi.testclient import TestClient

from helao.core.drivers.helao_driver import DriverPoller, DriverResponse, HelaoDriver
from helao.helpers.helao_logging import ALERT_LEVEL

EXPECTED = ["__init__", "_base_hook", "connect", "poller", "dyn_endpoints"]


def _make(
    record: list, *, connect_on_startup: bool, connect_raises=False, init_raises=False
):
    class FakeDriver(HelaoDriver):
        def __init__(self, config: dict = {}):
            super().__init__(config=config)
            record.append("__init__")
            if init_raises:
                raise RuntimeError("constructor failed")

        @property
        def _base_hook(self):
            return getattr(self, "_hook", None)

        @_base_hook.setter
        def _base_hook(self, value):
            record.append("_base_hook")
            self._hook = value

        def connect(self) -> DriverResponse:
            record.append("connect")
            if connect_raises:
                raise RuntimeError("no device")
            return DriverResponse()

        def get_status(self) -> DriverResponse:
            return DriverResponse()

        def stop(self) -> DriverResponse:
            return DriverResponse()

        def reset(self) -> DriverResponse:
            return DriverResponse()

        def disconnect(self) -> DriverResponse:
            return DriverResponse()

    FakeDriver.connect_on_startup = connect_on_startup

    class FakePoller(DriverPoller):
        def __init__(self, driver, wait_time=0.1):
            super().__init__(driver, wait_time)
            record.append("poller")

        def get_data(self) -> DriverResponse:
            return DriverResponse()

    async def _dyn(app):
        record.append("dyn_endpoints")

    return FakeDriver, FakePoller, _dyn


def _host(record: list, **kw):
    from helao.hexagon.app.action_host import ActionHost
    from helao.hexagon.app.wiring import PortWiring

    driver, poller, dyn = _make(record, **kw)
    cfg = {
        "root": tempfile.mkdtemp(prefix="helao_host_lifecycle_"),
        "servers": {"SIM": {"host": "127.0.0.1", "port": 8761, "params": {}}},
    }

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
    return ActionHost(
        server_key="SIM",
        server_title="SIM",
        description="host lifecycle test",
        version=1.0,
        driver_classes=[driver],
        dyn_endpoints=dyn,
        poller_class=poller,
        wiring=wiring,
        helao_cfg=cfg,
    )


def _wait_for(record: list, item: str, timeout: float = 2.0) -> None:
    end = time.time() + timeout
    while item not in record and time.time() < end:
        time.sleep(0.02)


def test_flag_true_orders_connect_before_poller_and_dyn_endpoints() -> None:
    record: list = []
    with TestClient(_host(record, connect_on_startup=True)):
        _wait_for(record, "dyn_endpoints")
    assert record == EXPECTED


def test_flag_false_never_connects() -> None:
    record: list = []
    with TestClient(_host(record, connect_on_startup=False)):
        _wait_for(record, "dyn_endpoints")
    assert record == [x for x in EXPECTED if x != "connect"]


def test_connect_exception_is_logged_and_startup_continues(caplog) -> None:
    from helao.hexagon.app import action_host

    record: list = []
    lg = action_host.LOGGER
    old_level = lg.level
    lg.setLevel(logging.DEBUG)
    lg.addHandler(caplog.handler)
    try:
        with TestClient(
            _host(record, connect_on_startup=True, connect_raises=True)
        ) as c:
            _wait_for(record, "dyn_endpoints")
            status = c.post("/get_status")
    finally:
        lg.removeHandler(caplog.handler)
        lg.setLevel(old_level)
    assert record == EXPECTED
    errors = [
        r
        for r in caplog.records
        if "connect() at startup raised" in r.getMessage()
        and r.levelno == logging.ERROR
    ]
    assert len(errors) == 1 and errors[0].exc_info
    alerts = [r for r in caplog.records if r.levelno == ALERT_LEVEL]
    assert len(alerts) == 1 and "no device" in alerts[0].getMessage()
    assert status.status_code == 200


def test_constructor_exception_still_propagates() -> None:
    record: list = []
    with pytest.raises(RuntimeError, match="constructor failed"):
        with TestClient(_host(record, connect_on_startup=True, init_raises=True)):
            pass
