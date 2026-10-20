"""Poller-backed drivers open their device in ``connect()``, not at construction.

The host calls ``connect()`` at startup (``connect_on_startup``), after setting
``_base_hook`` and before the paired ``DriverPoller`` exists, so the port is open
before the first poll. A failed connect leaves the driver disconnected under a
running poller; the poller's ``get_data()`` must tolerate that (CM0134, SprintIR).
MeerstetterTEC still opens at construction until its own increment; see
test_simdos_connect_in_init.py for the station instance.
"""

import sys
import types

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


def test_tec_opens_at_construction(monkeypatch):
    monkeypatch.setattr(mecom_driver, "MeCom", _Session)
    drv = mecom_driver.MeerstetterTEC(config={"channel": 1, "port": "COM3"})
    assert drv._session is not None and drv.address == 1


def test_tec_with_a_missing_port_fails_once_without_raising(monkeypatch):
    calls = []

    def refuse(serialport, timeout):
        calls.append(serialport)
        raise OSError("could not open port")

    monkeypatch.setattr(mecom_driver, "MeCom", refuse)
    drv = mecom_driver.MeerstetterTEC(config={"channel": 1, "port": "COM3"})
    assert drv._session is None
    assert len(calls) == 1
