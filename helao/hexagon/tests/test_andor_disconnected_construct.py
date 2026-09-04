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
        raise AssertionError("no vendor loader may run at construction")

    monkeypatch.setattr(andor_driver, "_load_camera", _boom_load)
    monkeypatch.setattr(andor_driver, "_load_spectrograph", _boom_load)
    AndorDriver(config={})  # must not raise / must not call either loader
    assert called["load"] == 0


def test_connect_creates_sdk_once_then_reuses(monkeypatch):
    made = {"camera_loads": 0, "sdks": 0}

    class _FakeCam:
        pass

    class _FakeSDK:
        def __init__(self):
            made["sdks"] += 1

        def GetCamera(self, dev_id):
            return _FakeCam()

    monkeypatch.setattr(
        andor_driver,
        "_load_camera",
        lambda: made.__setitem__("camera_loads", made["camera_loads"] + 1),
    )
    monkeypatch.setattr(andor_driver, "AndorSDK3", _FakeSDK, raising=False)

    d = AndorDriver(config={})
    # stub out the post-open metadata calls (they need real camera COM)
    monkeypatch.setattr(d, "setup_image", lambda: 1024)
    monkeypatch.setattr(d, "setup_spectroscope", lambda pw: [0.0])
    monkeypatch.setattr(d, "get_meta_data", lambda: (1, 1, 1, 1))

    assert d.sdk3 is None
    d.connect()
    assert made["sdks"] == 1 and made["camera_loads"] == 1  # created on first connect
    first_sdk = d.sdk3
    d.connect()
    assert made["sdks"] == 1  # reused, not recreated
    assert d.sdk3 is first_sdk


def test_connect_loads_the_camera(monkeypatch):
    """connect() binds the camera SDK before opening the device."""
    loaded = {"camera": 0}

    class _FakeCam:
        pass

    class _FakeSDK:
        def GetCamera(self, dev_id):
            return _FakeCam()

    monkeypatch.setattr(
        andor_driver, "_load_camera", lambda: loaded.__setitem__("camera", 1)
    )
    monkeypatch.setattr(andor_driver, "AndorSDK3", _FakeSDK, raising=False)

    d = AndorDriver(config={})
    monkeypatch.setattr(d, "setup_image", lambda: 1024)
    monkeypatch.setattr(d, "setup_spectroscope", lambda pw: [0.0])
    monkeypatch.setattr(d, "get_meta_data", lambda: (1, 1, 1, 1))

    d.connect()
    assert loaded["camera"] == 1


def test_connect_still_reaches_the_spectrograph_until_the_class_split(monkeypatch):
    """Splitting the loader did NOT by itself free connect() of the spectrograph.

    connect() calls setup_spectroscope(), which calls _load_spectrograph().
    So a camera-only station still cannot get through connect() yet. This
    test pins that honestly rather than hiding it behind a stub -- an
    earlier version stubbed setup_spectroscope and could not fail.

    INVERT THIS TEST when connect() stops calling setup_spectroscope and
    calls an overridable wavelength hook instead. At that point a
    calibrated driver's connect() must load the camera and NOT the
    spectrograph, and this assertion becomes == 0 on that subclass.
    """
    loaded = {"camera": 0, "spectrograph": 0}

    class _FakeCam:
        pass

    class _FakeSDK:
        def GetCamera(self, dev_id):
            return _FakeCam()

    monkeypatch.setattr(
        andor_driver, "_load_camera", lambda: loaded.__setitem__("camera", 1)
    )
    monkeypatch.setattr(
        andor_driver,
        "_load_spectrograph",
        lambda: loaded.__setitem__("spectrograph", 1),
    )
    monkeypatch.setattr(andor_driver, "AndorSDK3", _FakeSDK, raising=False)

    d = AndorDriver(config={})
    monkeypatch.setattr(d, "setup_image", lambda: 1024)
    monkeypatch.setattr(d, "get_meta_data", lambda: (1, 1, 1, 1))
    # setup_spectroscope is deliberately NOT stubbed -- it is the path under test.

    resp = d.connect()
    assert loaded["camera"] == 1
    assert loaded["spectrograph"] == 1, "connect() reaches the spectrograph today"
    # ATSpectrograph is never bound (the loader is a no-op lambda), so
    # setup_spectroscope raises NameError into connect()'s broad except.
    assert resp.response == "failed"
