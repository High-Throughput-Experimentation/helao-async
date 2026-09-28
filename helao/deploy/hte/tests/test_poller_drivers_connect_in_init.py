"""Poller-backed drivers must open their device at construction.

ActionHost builds the driver and never calls connect(), while the paired
DriverPoller starts polling immediately. A device opened only in connect()
stays closed for the life of the server (CM0134, MeerstetterTEC; see
test_simdos_connect_in_init.py for the station instance).
"""

import sys
import types

import helao.deploy.hte.drivers.sensor.cm0134_driver as cm0134
import helao.deploy.hte.drivers.temperature_control.mecom_driver as mecom_driver


class _Inst:
    def __init__(self, device, address):
        self.device = device
        self.serial = types.SimpleNamespace(baudrate=None)


def test_cm0134_opens_at_construction(monkeypatch):
    fake = types.SimpleNamespace(Instrument=_Inst)
    monkeypatch.setitem(sys.modules, "minimalmodbus", fake)
    drv = cm0134.CM0134(config={"device": "COM7", "address": 254})
    assert drv.inst is not None and drv.inst.device == "COM7"


def test_cm0134_without_a_device_does_not_raise_or_poll(monkeypatch):
    monkeypatch.setitem(sys.modules, "minimalmodbus", None)  # import fails
    drv = cm0134.CM0134(config={"device": "COM7"})
    assert drv.inst is None
    assert drv.read_o2_ppm() is None


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
