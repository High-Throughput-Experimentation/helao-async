"""KinesisMotor opens its axes in ``connect()``, which the host calls at startup.

Construction opens nothing. A failed startup connect leaves ``motors`` empty under a
running poller, and ``KinesisPoller.get_data()`` (which publishes
``KinesisMotor.get_status()``) must stay a clean, empty success rather than an
error, so a missing controller does not log an ERROR traceback every cycle.
"""

import helao.deploy.hte.drivers.motion.kinesis_driver as kd
from helao.core.drivers.helao_driver import DriverResponse, DriverResponseType

AXIS = {"serial_no": "1", "pos_scale": 1.0, "vel_scale": 1.0, "acc_scale": 1.0}
CONFIG = {"axes": {"x": AXIS}}


def test_the_host_connects_the_motor():
    assert kd.KinesisMotor.connect_on_startup is True


def test_construction_opens_no_axis(monkeypatch):
    opened = []

    def _motor(conn=None, scale=None):
        opened.append(conn)
        return object()

    monkeypatch.setattr(kd.Thorlabs, "KinesisMotor", _motor)
    drv = kd.KinesisMotor(config=CONFIG)
    assert opened == [] and drv.motors == {}
    drv.connect()
    assert opened == ["1"] and list(drv.motors) == ["x"]


def test_poller_survives_a_disconnected_driver():
    drv = kd.KinesisMotor(config=CONFIG)
    assert drv.motors == {}  # never connected
    poller = kd.KinesisPoller.__new__(kd.KinesisPoller)
    poller.driver = drv
    for _ in range(3):
        resp = poller.get_data()
        assert isinstance(resp, DriverResponse)
        assert resp.response == DriverResponseType.success and resp.data == {}
