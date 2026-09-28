"""SIMDOS must open its serial port at construction.

ActionHost builds the driver and never calls connect(), so a port opened only
in connect() stayed None for the life of the server (ccsi2 DOSEPUMP,
2026-09-28: ``'NoneType' object has no attribute 'write'`` in set_mode).
"""

import pytest

import helao.deploy.hte.drivers.pump.simdos_driver as simdos


def test_port_is_open_after_construction(monkeypatch):
    opened = []
    monkeypatch.setattr(simdos.serial, "Serial", lambda **kw: opened.append(kw) or kw)
    drv = simdos.SIMDOS(config={"port": "COM7", "address": 1})
    assert drv.com is not None
    assert opened[0]["port"] == "COM7"


def test_a_failed_open_gives_a_clear_error_not_a_none_attribute(monkeypatch):
    def refuse(**kw):
        raise OSError("port busy")

    monkeypatch.setattr(simdos.serial, "Serial", refuse)
    drv = simdos.SIMDOS(config={"port": "COM7", "address": 1})
    with pytest.raises(RuntimeError, match="not open"):
        drv.send("?SS1")
