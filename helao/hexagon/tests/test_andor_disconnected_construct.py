"""AndorDriver disconnected-construct guard (P3a-2 constructor-connect fix).

Before P3a-2, ``AndorDriver.__init__`` instantiated the vendor SDK
(``AndorSDK3()``) and opened the camera (``connect()``), so the driver could
not be constructed without the Andor runtime + hardware. The fix relocates
both to ``connect()`` (called by ``andor_server.andor_dyn_endpoints`` at
startup). These tests pin that the constructor touches no vendor runtime and
that the SDK handle is created lazily, create-once.

Real camera behavior remains an at-station gate; this is construct-tier only.
Both subclasses are covered: the base is abstract and cannot be constructed.
"""

import pytest

from helao.deploy.hte.drivers.spec.andor import driver as andor_driver
from helao.deploy.hte.drivers.spec.andor import spectrograph as andor_spectrograph
from helao.deploy.hte.drivers.spec.andor.driver import AndorDriver
from helao.deploy.hte.drivers.spec.andor.spectrograph import AndorSpectrographDriver


def test_the_base_is_abstract():
    """A base that could be constructed would silently have no wavelengths."""
    with pytest.raises(TypeError, match="_wavelengths"):
        AndorDriver(config={})  # type: ignore[abstract]


def test_construct_without_sdk_or_hardware():
    d = AndorSpectrographDriver(config={"dev_id": 2})
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
    monkeypatch.setattr(andor_spectrograph, "_load_spectrograph", _boom_load)
    AndorSpectrographDriver(config={})
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

    d = AndorSpectrographDriver(config={})
    # stub out the post-open metadata calls (they need real camera COM)
    monkeypatch.setattr(d, "setup_image", lambda: 1024)
    monkeypatch.setattr(d, "_wavelengths", lambda: [0.0])
    monkeypatch.setattr(d, "get_meta_data", lambda: (1, 1, 1, 1))

    assert d.sdk3 is None
    d.connect()
    assert made["sdks"] == 1 and made["camera_loads"] == 1  # created on first connect
    first_sdk = d.sdk3
    d.connect()
    assert made["sdks"] == 1  # reused, not recreated
    assert d.sdk3 is first_sdk


def test_the_spectrograph_variant_still_loads_the_spectrograph_on_connect(monkeypatch):
    """This subclass's ``_wavelengths`` IS ``setup_spectroscope``.

    The class split freed the *base* of the spectrograph, not this variant:
    ``AndorSpectrographDriver._wavelengths`` calls ``setup_spectroscope``,
    which calls ``_load_spectrograph``. So a station running this class still
    needs ``pyAndorSpectrograph``, and that is pinned here honestly rather
    than hidden behind a stubbed ``_wavelengths`` -- a stub would make the
    assertion pass no matter what the class did.

    The camera-only end of the split is asserted by
    :func:`test_the_base_is_abstract` here, and end-to-end by the calibrated
    subclass's own tests once it exists.
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
        andor_spectrograph,
        "_load_spectrograph",
        lambda: loaded.__setitem__("spectrograph", 1),
    )
    monkeypatch.setattr(andor_driver, "AndorSDK3", _FakeSDK, raising=False)

    d = AndorSpectrographDriver(config={})
    monkeypatch.setattr(d, "setup_image", lambda: 1024)
    monkeypatch.setattr(d, "get_meta_data", lambda: (1, 1, 1, 1))
    # _wavelengths is deliberately NOT stubbed -- it is the path under test.

    resp = d.connect()
    assert loaded["camera"] == 1
    assert loaded["spectrograph"] == 1, "this variant reaches the spectrograph"
    # ATSpectrograph is never bound (the loader is a no-op lambda), so
    # setup_spectroscope raises NameError into connect()'s broad except.
    assert resp.response == "failed"
