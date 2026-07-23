"""AndorDriver disconnected-construct guard (P3a-2 constructor-connect fix).

Before P3a-2, ``AndorDriver.__init__`` instantiated the vendor SDK
(``AndorSDK3()``) and opened the camera (``connect()``), so the driver could
not be constructed without the Andor runtime + hardware. The fix relocates
both to ``connect()`` (called by ``andor_server.andor_dyn_endpoints`` at
startup). These tests pin that the constructor touches no vendor runtime and
that the SDK handle is created lazily, create-once.

Real camera behavior remains an at-station gate; this is construct-tier only.
"""

from helao.deploy.hte.drivers.spec.andor import driver as andor_driver
from helao.deploy.hte.drivers.spec.andor.driver import AndorDriver


def test_construct_without_sdk_or_hardware():
    d = AndorDriver(config={"dev_id": 2})
    assert d.sdk3 is None  # no AndorSDK3() at construction
    assert d.cam is None  # camera not opened
    assert d.wl_arr is None
    assert d.device_id == 2
    assert d.ready is True


def test_construct_does_not_load_vendor_runtime(monkeypatch):
    called = {"load": 0}

    def _boom_load():
        called["load"] += 1
        raise AssertionError("_load_andor must not run at construction")

    monkeypatch.setattr(andor_driver, "_load_andor", _boom_load)
    AndorDriver(config={})  # must not raise / must not call _load_andor
    assert called["load"] == 0


def test_connect_creates_sdk_once_then_reuses(monkeypatch):
    made = {"loads": 0, "sdks": 0}

    class _FakeCam:
        pass

    class _FakeSDK:
        def __init__(self):
            made["sdks"] += 1

        def GetCamera(self, dev_id):
            return _FakeCam()

    monkeypatch.setattr(
        andor_driver,
        "_load_andor",
        lambda: made.__setitem__("loads", made["loads"] + 1),
    )
    monkeypatch.setattr(andor_driver, "AndorSDK3", _FakeSDK, raising=False)

    d = AndorDriver(config={})
    # stub out the post-open metadata calls (they need real camera COM)
    monkeypatch.setattr(d, "setup_image", lambda: 1024)
    monkeypatch.setattr(d, "setup_spectroscope", lambda pw: [0.0])
    monkeypatch.setattr(d, "get_meta_data", lambda: (1, 1, 1, 1))

    assert d.sdk3 is None
    d.connect()
    assert made["sdks"] == 1 and made["loads"] == 1  # created on first connect
    first_sdk = d.sdk3
    d.connect()
    assert made["sdks"] == 1  # reused, not recreated
    assert d.sdk3 is first_sdk
