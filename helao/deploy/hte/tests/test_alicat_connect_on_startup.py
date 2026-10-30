"""AliCatMFC opens its controllers in ``connect()``, which the host calls at startup.

Construction opens nothing. A failed startup connect leaves ``fcs`` empty under a
running poller, and the poller's ``get_data()`` must keep returning a
``DriverResponse`` without raising.
"""

import helao.deploy.hte.drivers.mfc.alicat_driver as alicat
from helao.core.drivers.helao_driver import DriverResponse

CONFIG = {"devices": {"mfc1": {"port": "COM1", "unit_id": "A"}}}


def test_the_host_connects_the_mfc():
    assert alicat.AliCatMFC.connect_on_startup is True


def test_construction_opens_no_controller(monkeypatch):
    opened = []
    monkeypatch.setattr(
        alicat,
        "FlowController",
        lambda **kw: opened.append(kw) or (_ for _ in ()).throw(OSError("busy")),
    )
    drv = alicat.AliCatMFC(config=CONFIG)
    assert opened == [] and drv.fcs == {}
    drv.connect()  # fails, logged, never raises
    assert len(opened) == 1


def test_poller_survives_a_disconnected_driver():
    drv = alicat.AliCatMFC(config=CONFIG)
    assert drv.fcs == {}  # never connected
    poller = alicat.AliCatMFCPoller.__new__(alicat.AliCatMFCPoller)
    poller.driver = drv
    for _ in range(3):
        assert isinstance(poller.get_data(), DriverResponse)
