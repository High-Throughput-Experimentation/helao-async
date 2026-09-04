"""The lamp-calibrated Andor variant, construct- and load-tier only.

The cold-start rule is the load-bearing part: connect() must SUCCEED with no
calibration on disk, because the calibration action runs on this same server
and a refusing connect() would make the station uncalibratable forever. It is
`acquire` that must refuse, not `connect`.
"""

import json

import numpy as np
import pytest

from helao.deploy.hte.drivers.spec.andor import driver as andor_driver
from helao.deploy.hte.drivers.spec.andor import wl_calibration as wlc
from helao.deploy.hte.drivers.spec.andor.calibrated import AndorCalibratedDriver

CALIB = wlc.WavelengthCalibration(
    model=wlc.MODEL_POLY,
    coeffs=[400.0, 0.2],
    n_pixels=16,
    fit_rms_nm=0.02,
    n_lines=5,
    lamp="Hg-Ar",
    created="2026-09-04T00:00:00Z",
    source_action_uuid=None,
)


def _driver(tmp_path, **extra):
    config = {"dev_id": 0, "states_root": str(tmp_path), "host": "teststation"}
    config.update(extra)
    return AndorCalibratedDriver(config=config, server_key="ANDOR")


def test_construct_without_sdk_or_calibration(tmp_path):
    d = _driver(tmp_path)
    assert d.sdk3 is None
    assert d.cam is None
    assert d.wl_arr is None
    assert d.ready is True


def test_construct_does_not_import_the_spectrograph_module(tmp_path):
    """The whole point: this station has no pyAndorSpectrograph installed."""
    import sys

    sys.modules.pop("helao.deploy.hte.drivers.spec.andor.spectrograph", None)
    _driver(tmp_path)
    assert "helao.deploy.hte.drivers.spec.andor.spectrograph" not in sys.modules


def test_calibration_file_follows_the_convention(tmp_path):
    d = _driver(tmp_path)
    assert d.calibration_file().name == "teststation_ANDOR_andor_wl_calib.json"


def test_wavelengths_are_none_when_no_calibration_exists(tmp_path):
    d = _driver(tmp_path)
    assert d._wavelengths() is None


def test_wavelengths_come_from_the_persisted_calibration(tmp_path):
    d = _driver(tmp_path)
    wlc.save(CALIB, d.calibration_file())
    wl = d._wavelengths()
    assert wl is not None
    assert wl.shape == (16,)
    assert wl[0] == pytest.approx(400.0)
    assert wl[15] == pytest.approx(400.0 + 0.2 * 15)


def test_connect_succeeds_without_a_calibration(tmp_path, monkeypatch, caplog):
    """A refusing connect() would make the station uncalibratable forever."""

    class _FakeCam:
        pass

    class _FakeSDK:
        def GetCamera(self, dev_id):
            return _FakeCam()

    monkeypatch.setattr(andor_driver, "_load_camera", lambda: None)
    monkeypatch.setattr(andor_driver, "AndorSDK3", _FakeSDK, raising=False)

    d = _driver(tmp_path)
    monkeypatch.setattr(d, "setup_image", lambda: 1024)
    monkeypatch.setattr(d, "get_meta_data", lambda: (1, 1, 1, 1))

    resp = d.connect()
    assert resp.response == "success"
    assert d.wl_arr is None


def test_an_unreadable_model_is_refused_not_guessed(tmp_path):
    d = _driver(tmp_path)
    path = d.calibration_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "model": "chebyshev",
                "coeffs": [1.0],
                "n_pixels": 4,
                "fit_rms_nm": 0.0,
                "n_lines": 0,
                "lamp": "x",
                "created": "2026-09-04T00:00:00Z",
                "source_action_uuid": None,
            }
        )
    )
    with pytest.raises(wlc.UnknownCalibrationModel):
        d._wavelengths()
