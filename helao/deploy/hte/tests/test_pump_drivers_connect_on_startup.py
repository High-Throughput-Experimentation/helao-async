"""SIMDOS and KDS100 connect at host startup, and their pollers tolerate a failed connect.

A failed startup connect leaves the driver disconnected under a running poller, so
each poller's ``get_data()`` must return a ``DriverResponse`` without raising. The
SIMDOS fault sweep reads ``self._base_hook.executors`` (a ``DriverHostPort`` member).
"""

import types
from typing import Any

import helao.deploy.hte.drivers.pump.legato_driver as legato
import helao.deploy.hte.drivers.pump.simdos_driver as simdos
from helao.core.drivers.helao_driver import DriverResponse


def test_the_host_connects_both_pumps():
    assert simdos.SIMDOS.connect_on_startup is True
    assert legato.KDS100.connect_on_startup is True


def test_simdos_poller_survives_a_disconnected_driver():
    drv = simdos.SIMDOS(config={"port": "COM7", "address": 1})
    assert drv.com is None  # never connected
    poller = simdos.SIMDOSPoller.__new__(simdos.SIMDOSPoller)
    poller.driver = drv
    for _ in range(3):
        assert isinstance(poller.get_data(), DriverResponse)


def test_kds100_poller_survives_a_disconnected_driver(monkeypatch):
    drv = legato.KDS100(config={"port": "COM7", "pumps": {"p": {"address": 1}}})
    assert drv.sio is None  # never connected
    sent = []
    monkeypatch.setattr(drv, "_send_sync", lambda *a, **k: sent.append(a) or [])
    poller = legato.KDS100Poller.__new__(legato.KDS100Poller)
    poller.driver = drv
    for _ in range(3):
        assert isinstance(poller.get_data(), DriverResponse)
    assert sent == []  # the short-circuit skips the bus (and its per-cycle log)


class _Executor:
    def __init__(self) -> None:
        self.stopped = 0

    def stop_action_task(self) -> None:
        self.stopped += 1


def test_simdos_fault_stops_host_executors(monkeypatch):
    drv = simdos.SIMDOS(config={"port": "COM7", "address": 1})
    drv.com = object()  # past the disconnected short-circuit
    for name in ("get_opstat", "get_sysstat", "get_runstat", "get_dispstat"):
        monkeypatch.setattr(drv, name, lambda: {})
    monkeypatch.setattr(drv, "get_faults", lambda: {"overpressure": ("fault", 1)})
    executors = {1: _Executor(), 2: _Executor()}
    host: Any = types.SimpleNamespace(executors=executors)
    poller = simdos.SIMDOSPoller.__new__(simdos.SIMDOSPoller)
    poller.driver = drv
    poller._base_hook = host
    poller.get_data()
    assert [e.stopped for e in executors.values()] == [1, 1]


def test_simdos_without_a_fault_leaves_executors_running(monkeypatch):
    drv = simdos.SIMDOS(config={"port": "COM7", "address": 1})
    drv.com = object()
    for name in ("get_opstat", "get_sysstat", "get_runstat", "get_dispstat"):
        monkeypatch.setattr(drv, name, lambda: {})
    monkeypatch.setattr(drv, "get_faults", lambda: {"overpressure": ("fault", 0)})
    executors = {1: _Executor()}
    host: Any = types.SimpleNamespace(executors=executors)
    poller = simdos.SIMDOSPoller.__new__(simdos.SIMDOSPoller)
    poller.driver = drv
    poller._base_hook = host
    poller.get_data()
    assert executors[1].stopped == 0
