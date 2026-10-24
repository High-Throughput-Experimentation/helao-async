"""SIMDOS opens its serial port in ``connect()``, which the host calls at startup.

``connect_on_startup`` makes the host connect before the poller exists, so the port
is open before the first poll (ccsi2 DOSEPUMP, 2026-09-28: ``'NoneType' object has
no attribute 'write'`` in set_mode, when nothing opened it). Construction opens
nothing.
"""

import pytest

import helao.deploy.hte.drivers.pump.simdos_driver as simdos


def test_port_is_open_after_connect(monkeypatch):
    opened = []
    monkeypatch.setattr(simdos.serial, "Serial", lambda **kw: opened.append(kw) or kw)
    drv = simdos.SIMDOS(config={"port": "COM7", "address": 1})
    assert drv.com is None and opened == []  # construction opens nothing
    drv.connect()
    assert drv.com is not None
    assert opened[0]["port"] == "COM7"


def test_a_failed_open_gives_a_clear_error_not_a_none_attribute(monkeypatch):
    def refuse(**kw):
        raise OSError("port busy")

    monkeypatch.setattr(simdos.serial, "Serial", refuse)
    drv = simdos.SIMDOS(config={"port": "COM7", "address": 1})
    drv.connect()
    with pytest.raises(RuntimeError, match="not open"):
        drv.send("?SS1")
