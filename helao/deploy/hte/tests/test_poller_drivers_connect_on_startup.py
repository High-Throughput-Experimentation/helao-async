"""Poller-backed drivers open their device in ``connect()``, not at construction.

The host calls ``connect()`` at startup (``connect_on_startup``), after setting
``_base_hook`` and before the paired ``DriverPoller`` exists, so the port is open
before the first poll. A failed connect leaves the driver disconnected under a
running poller; the poller's ``get_data()`` must tolerate that (CM0134, SprintIR).
MeerstetterTEC is the one exception: its ``get_data()`` re-attempts the MeCom open
and raises while disconnected, so its poller survives by ``DriverPoller``'s own
error handling. See test_simdos_connect_on_startup.py for the station instance.
"""

import asyncio
import sys
import types

import pytest

from helao.core.drivers.helao_driver import DriverResponse
import helao.deploy.hte.drivers.sensor.cm0134_driver as cm0134
import helao.deploy.hte.drivers.sensor.sprintir_driver as sprintir
import helao.deploy.hte.drivers.temperature_control.mecom_driver as mecom_driver


class _Inst:
    def __init__(self, device, address):
        self.device = device
        self.serial = types.SimpleNamespace(baudrate=None)


def test_cm0134_opens_on_connect(monkeypatch):
    fake = types.SimpleNamespace(Instrument=_Inst)
    monkeypatch.setitem(sys.modules, "minimalmodbus", fake)
    drv = cm0134.CM0134(config={"device": "COM7", "address": 254})
    assert drv.inst is None  # construction opens nothing
    drv.connect()
    assert drv.inst is not None and drv.inst.device == "COM7"


def test_cm0134_without_a_device_does_not_raise_or_poll(monkeypatch):
    monkeypatch.setitem(sys.modules, "minimalmodbus", None)  # import fails
    drv = cm0134.CM0134(config={"device": "COM7"})
    drv.connect()
    assert drv.inst is None
    assert drv.read_o2_ppm() is None


def test_the_host_connects_cm0134_and_sprintir():
    assert cm0134.CM0134.connect_on_startup is True
    assert sprintir.SprintIR.connect_on_startup is True


def test_cm0134_poller_survives_a_disconnected_driver(monkeypatch):
    """A failed connect leaves the driver closed under a running poller."""
    monkeypatch.setitem(sys.modules, "minimalmodbus", None)  # import fails
    drv = cm0134.CM0134(config={"device": "COM7"})
    drv.connect()  # fails, logged
    poller = cm0134.CM0134Poller.__new__(cm0134.CM0134Poller)
    poller.driver = drv
    for _ in range(3):
        assert isinstance(poller.get_data(), DriverResponse)


def test_sprintir_opens_on_connect_and_its_poller_survives_a_failed_one(monkeypatch):
    class _Serial:
        def __init__(self, **kw):
            raise OSError("could not open port")

    monkeypatch.setattr(sprintir.serial, "Serial", _Serial)
    drv = sprintir.SprintIR(config={"port": "COM12"})
    assert drv.com is None  # construction opens nothing
    drv.connect()  # fails, logged, never raises
    assert drv.com is None
    poller = sprintir.SprintIRPoller.__new__(sprintir.SprintIRPoller)
    poller.driver = drv
    for _ in range(3):
        assert isinstance(poller.get_data(), DriverResponse)


class _Session:
    def __init__(self, serialport, timeout):
        self.port = serialport

    def identify(self):
        return 1


def test_tec_opens_on_connect(monkeypatch):
    monkeypatch.setattr(mecom_driver, "MeCom", _Session)
    drv = mecom_driver.MeerstetterTEC(config={"channel": 1, "port": "COM3"})
    assert drv._session is None  # construction opens nothing
    drv.connect()
    assert drv._session is not None and drv.address == 1


def test_tec_with_a_missing_port_fails_once_without_raising(monkeypatch):
    calls = []

    def refuse(serialport, timeout):
        calls.append(serialport)
        raise OSError("could not open port")

    monkeypatch.setattr(mecom_driver, "MeCom", refuse)
    drv = mecom_driver.MeerstetterTEC(config={"channel": 1, "port": "COM3"})
    assert calls == []  # construction opens nothing
    drv.connect()
    assert drv._session is None
    assert len(calls) == 1


def test_the_host_connects_the_tec():
    assert mecom_driver.MeerstetterTEC.connect_on_startup is True


@pytest.mark.asyncio
async def test_tec_poller_raises_while_disconnected_and_the_loop_survives(
    monkeypatch, caplog
):
    """Pre-settled exception: ``get_data()`` re-attempts the open and raises.

    That is today's behaviour. ``DriverPoller`` logs the first failure with a
    traceback and then every 100th, so three cycles log one line and the loop
    keeps running.
    """
    from helao.core.drivers import helao_driver

    def refuse(serialport, timeout):
        raise OSError("could not open port")

    monkeypatch.setattr(mecom_driver, "MeCom", refuse)
    drv = mecom_driver.MeerstetterTEC(config={"channel": 1, "port": "COM3"})
    drv.connect()  # fails, logged, never raises
    bare = mecom_driver.MeerstetterTECPoller.__new__(mecom_driver.MeerstetterTECPoller)
    bare.driver = drv
    with pytest.raises(OSError):
        bare.get_data()
    helao_driver.LOGGER.addHandler(caplog.handler)
    try:
        poller = mecom_driver.MeerstetterTECPoller(drv, 0.01)
        for _ in range(100):
            if any("get_data() raised" in r.getMessage() for r in caplog.records):
                await asyncio.sleep(0.15)
                break
            await asyncio.sleep(0.02)
        assert not poller.polling_task.done()  # the loop survived
        await poller.stop()
    finally:
        helao_driver.LOGGER.removeHandler(caplog.handler)
    failures = [r for r in caplog.records if "get_data() raised" in r.getMessage()]
    assert len(failures) == 1, f"expected one logged traceback, got {len(failures)}"


def test_tec_host_starts_and_shuts_down_after_a_raising_connect(
    monkeypatch, tmp_path, caplog
):
    """The one host-level proof that a formerly constructor-connect driver tears down.

    ``tec_server`` has no station, so this is its only end-to-end check. The host
    catches the raising ``connect()``, starts anyway, and shutdown must run on a
    driver that never connected.
    """
    import logging
    import time

    from fastapi.testclient import TestClient

    from helao.deploy.hte.servers.action import tec_server
    from helao.helpers import config_loader
    from helao.hexagon.app import action_host

    monkeypatch.setattr(
        config_loader,
        "CONFIG",
        {
            "root": str(tmp_path),
            "dummy": True,
            "simulation": True,
            "servers": {
                "TEC": {
                    "host": "127.0.0.1",
                    "port": 8008,
                    "group": "action",
                    "fast": "tec_server",
                    "params": {"channel": 1, "port": "COM3"},
                }
            },
        },
    )
    (tmp_path / "LOGS").mkdir()
    opens = []

    def refuse(serialport, timeout):
        opens.append(serialport)
        raise OSError("could not open port")

    monkeypatch.setattr(mecom_driver, "MeCom", refuse)

    def connect_raises(self):
        raise OSError("no device")

    monkeypatch.setattr(mecom_driver.MeerstetterTEC, "connect", connect_raises)
    app = tec_server.makeApp("TEC")
    lg = action_host.LOGGER
    old_level = lg.level
    lg.setLevel(logging.DEBUG)
    lg.addHandler(caplog.handler)
    try:
        with TestClient(app) as client:
            end = time.time() + 3
            while len(opens) < 2 and time.time() < end:
                time.sleep(0.05)
            status = client.post("/get_status")
            poller = app.poller
    finally:
        lg.removeHandler(caplog.handler)
        lg.setLevel(old_level)
    errors = [
        r
        for r in caplog.records
        if "connect() at startup raised" in r.getMessage()
        and r.levelno == logging.ERROR
    ]
    assert len(errors) == 1 and "MeerstetterTEC" in errors[0].getMessage()
    assert status.status_code == 200
    assert len(opens) >= 2  # the poller ran at least two cycles
    assert poller is not None and poller.polling_task.done()
    assert app._shutdown_task is not None
    retvals = app._shutdown_task.result()
    assert "shutdown" in retvals and "async_shutdown" in retvals
