"""The lamp-calibrated Andor variant, construct- and load-tier only.

The cold-start rule is the load-bearing part: connect() must SUCCEED with no
calibration on disk, because the calibration action runs on this same server
and a refusing connect() would make the station uncalibratable forever. It is
`acquire` that must refuse, not `connect`.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from helao.deploy.hte.drivers.spec.andor import driver as andor_driver
from helao.deploy.hte.drivers.spec.andor import wl_calibration as wlc
from helao.deploy.hte.drivers.spec.andor.calibrated import AndorCalibratedDriver
from helao.deploy.hte.drivers.spec.andor.driver import DEFAULT_LAMP_LINES_NM

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


def test_states_root_prefers_base_hook_helaodirs(tmp_path):
    """Branch 1: `_base_hook.helaodirs.states_root` wins, even over config."""

    class _FakeHelaodirs:
        states_root = str(tmp_path / "from_hook")

    class _FakeBaseHook:
        helaodirs = _FakeHelaodirs()

    d = _driver(tmp_path, states_root=str(tmp_path / "from_config"))
    d._base_hook = _FakeBaseHook()
    assert d.calibration_file().parent == tmp_path / "from_hook"


def test_states_root_falls_back_to_config_without_a_base_hook(tmp_path):
    """Branch 2: no `_base_hook`, so `config["states_root"]` is used."""
    d = _driver(tmp_path, states_root=str(tmp_path / "from_config"))
    assert getattr(d, "_base_hook", None) is None
    assert d.calibration_file().parent == tmp_path / "from_config"


def test_states_root_falls_back_to_cwd_relative_and_warns(
    tmp_path, monkeypatch, caplog
):
    """Branch 3: neither a hook nor a configured root -- loudly cwd-relative."""
    config = {"dev_id": 0, "host": "teststation"}
    d = AndorCalibratedDriver(config=config, server_key="ANDOR")
    monkeypatch.chdir(tmp_path)
    with caplog.at_level("WARNING"):
        path = d.calibration_file()
    assert path.parent == Path("STATES")
    assert any(
        "states_root" in r.getMessage() and str(tmp_path / "STATES") in r.getMessage()
        for r in caplog.records
    )


def _fake_lamp_frame(n_pixels, line_pixels):
    pixels = np.arange(n_pixels, dtype=float)
    counts = np.full(n_pixels, 100.0)
    for p in line_pixels:
        counts += 5000.0 * np.exp(-0.5 * ((pixels - p) / 2.0) ** 2)
    return counts


def test_the_default_lamp_line_table_is_usable(tmp_path):
    """A bare POST must be able to calibrate; the default must support the fit."""
    assert len(DEFAULT_LAMP_LINES_NM) >= 5
    assert DEFAULT_LAMP_LINES_NM == sorted(DEFAULT_LAMP_LINES_NM)


def test_run_wl_calibration_persists_and_reports(tmp_path, monkeypatch):
    d = _driver(tmp_path)
    line_pixels = [200, 700, 1300, 1900, 2400]
    true_nm = [400.0 + 0.2 * p for p in line_pixels]
    monkeypatch.setattr(
        d,
        "_capture_lamp_frame",
        lambda n_frames, exp_time: _fake_lamp_frame(2560, line_pixels),
    )

    resp = d.run_wl_calibration(true_nm, lamp="Hg-Ar", degree=1)
    assert resp.response == "success"
    assert resp.data["fit_rms_nm"] < 0.5
    assert resp.data["n_lines"] == 5
    assert resp.data["applied"] is True  # calibrated driver uses it live
    assert d.calibration_file().exists()


def test_run_wl_calibration_reports_failure_without_raising(tmp_path, monkeypatch):
    """An action handler must never see an exception out of the driver."""
    d = _driver(tmp_path)
    monkeypatch.setattr(
        d,
        "_capture_lamp_frame",
        lambda n_frames, exp_time: _fake_lamp_frame(2560, [200]),
    )
    resp = d.run_wl_calibration([400.0, 500.0, 600.0, 700.0, 800.0], degree=3)
    assert resp.response == "failed"
    assert not d.calibration_file().exists()
