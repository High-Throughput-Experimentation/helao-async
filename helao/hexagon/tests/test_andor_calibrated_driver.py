"""The lamp-calibrated Andor variant, construct- and load-tier only.

The cold-start rule is the load-bearing part: connect() must SUCCEED with no
calibration on disk, because the calibration action runs on this same server
and a refusing connect() would make the station uncalibratable forever. It is
`acquire` that must refuse, not `connect`.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from helao.deploy.hte.drivers.spec.andor import driver as andor_driver
from helao.deploy.hte.drivers.spec.andor import wl_calibration as wlc
from helao.deploy.hte.drivers.spec.andor.calibrated import AndorCalibratedDriver
from helao.deploy.hte.drivers.spec.andor import wl_fit

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
    # Not None: connect() substitutes the bare channel index so acquire can
    # run before the station has ever been calibrated. get_meta_data is
    # stubbed to report a 1-pixel AOI here, so the index is [0.0].
    assert d.wl_arr is not None
    assert list(d.wl_arr) == [0.0]
    assert d.wl_calibrated is False


def test_the_channel_index_is_one_entry_per_detector_column(tmp_path, monkeypatch):
    """The substitute axis must line up with the ch_* columns beside it."""

    class _FakeCam:
        pass

    class _FakeSDK:
        def GetCamera(self, dev_id):
            return _FakeCam()

    monkeypatch.setattr(andor_driver, "_load_camera", lambda: None)
    monkeypatch.setattr(andor_driver, "AndorSDK3", _FakeSDK, raising=False)

    d = _driver(tmp_path)
    monkeypatch.setattr(d, "setup_image", lambda: 1024)
    monkeypatch.setattr(d, "get_meta_data", lambda: (2560, 2160, 1, 1))

    d.connect()
    assert d.wl_arr is not None
    assert len(d.wl_arr) == 2560
    assert d.wl_arr[0] == 0.0 and d.wl_arr[-1] == 2559.0
    assert d.wl_calibrated is False


def test_a_real_calibration_is_not_replaced_by_the_index(tmp_path, monkeypatch):
    """The substitution must never overwrite a measured axis."""

    class _FakeCam:
        pass

    class _FakeSDK:
        def GetCamera(self, dev_id):
            return _FakeCam()

    monkeypatch.setattr(andor_driver, "_load_camera", lambda: None)
    monkeypatch.setattr(andor_driver, "AndorSDK3", _FakeSDK, raising=False)

    d = _driver(tmp_path)
    wlc.save(CALIB, d.calibration_file())
    monkeypatch.setattr(d, "setup_image", lambda: 1024)
    monkeypatch.setattr(d, "get_meta_data", lambda: (16, 1, 1, 1))

    d.connect()
    assert d.wl_calibrated is True
    assert d.wl_arr is not None
    assert d.wl_arr[0] == pytest.approx(400.0)


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


#: Enough anchors to seed a degree-4 fit. Their values do not matter in this
#: file: every test here stubs the fit itself, because what these tests are
#: about is the driver's gating -- refuse a bad residual, refuse a
#: non-monotonic axis, keep a .prev, apply live on the right variant. The
#: numerics that turn a frame into a calibration are `test_andor_wl_fit`'s
#: subject, and coupling both files to them would mean one fit change
#: breaking two suites for one reason.
ANCHORS = [[200 + 300 * i, 440.0 + 55.0 * i] for i in range(8)]


def _stub_fit(monkeypatch, **overrides):
    """Make `wl_fit.fit_wavelength` return a canned calibration."""
    fields = dict(
        model=wlc.MODEL_CHEB,
        coeffs=[660.0, 232.0, 6.0, 1.2, 0.4],
        domain=[0.0, 2559.0],
        n_pixels=2560,
        fit_rms_nm=0.01,
        max_residual_nm=0.02,
        n_lines=30,
        n_rejected=2,
        n_saturated=0,
        medium="air",
        lamp="Ocean Insight KR-2",
        created="2026-09-07T00:00:00+00:00",
        wl_source="unknown",
        source_action_uuid=None,
    )
    fields.update(overrides)

    def _fake(counts, anchors, **kwargs):
        return wlc.WavelengthCalibration(
            **{**fields, "wl_source": kwargs.get("wl_source", fields["wl_source"])}
        )

    monkeypatch.setattr(wl_fit, "fit_wavelength", _fake)


def test_the_bundled_catalogue_is_krypton_in_air():
    """The lamp list is data, not a guess, and its medium is recorded."""
    from helao.deploy.hte.drivers.spec.andor import kr_lines

    assert kr_lines.MEDIUM == "air"
    assert len(kr_lines.KR_LINES_AIR_NM) > 50
    lo, hi = kr_lines.LAMP_RANGE_NM
    assert all(lo <= w <= hi for w, _i, _s in kr_lines.KR_LINES_AIR_NM)
    assert not hasattr(
        andor_driver, "DEFAULT_LAMP_LINES_NM"
    ), "the old name read as a default and must not come back"
    assert not hasattr(
        andor_driver, "HG_AR_REFERENCE_LINES_NM"
    ), "the Hg-Ar menu is superseded by the krypton catalogue"


def test_run_wl_calibration_persists_and_reports(tmp_path, monkeypatch):
    d = _driver(tmp_path)
    _stub_fit(monkeypatch)
    line_pixels = [200, 700, 1300, 1900, 2400]
    true_nm = [400.0 + 0.2 * p for p in line_pixels]
    monkeypatch.setattr(
        d,
        "_capture_lamp_frame",
        lambda n_frames, exp_time: _fake_lamp_frame(2560, line_pixels),
    )

    resp = d.run_wl_calibration(ANCHORS)
    assert resp.response == "success"
    assert resp.data["fit_rms_nm"] < 0.5
    assert resp.data["n_lines"] == 30
    assert resp.data["applied"] is True  # calibrated driver uses it live
    assert d.calibration_file().exists()


def test_run_wl_calibration_reports_failure_without_raising(tmp_path, monkeypatch):
    """An action handler must never see an exception out of the driver."""
    d = _driver(tmp_path)
    _stub_fit(monkeypatch, fit_rms_nm=99.0, max_residual_nm=99.0)
    monkeypatch.setattr(
        d,
        "_capture_lamp_frame",
        lambda n_frames, exp_time: _fake_lamp_frame(2560, [200]),
    )
    resp = d.run_wl_calibration(ANCHORS)
    assert resp.response == "failed"
    assert not d.calibration_file().exists()


def test_a_successful_calibration_takes_effect_without_a_reconnect(
    tmp_path, monkeypatch
):
    """`applied: True` must mean applied NOW, not at the next connect().

    The driver reports `applied` from `uses_lamp_calibration`, which is a
    property of the variant, not of what just happened. Left unrefreshed,
    `wl_arr` stays whatever connect() found -- so an operator sees
    `applied: true` and then watches `acquire` refuse anyway, which reads as
    a broken station rather than as a missing restart.
    """
    d = _driver(tmp_path)
    _stub_fit(monkeypatch)
    assert d.wl_arr is None, "no calibration on disk yet"
    line_pixels = [200, 700, 1300, 1900, 2400]
    true_nm = [400.0 + 0.2 * p for p in line_pixels]
    monkeypatch.setattr(
        d,
        "_capture_lamp_frame",
        lambda n_frames, exp_time: _fake_lamp_frame(2560, line_pixels),
    )

    resp = d.run_wl_calibration(ANCHORS)

    assert resp.data["applied"] is True
    # no connect() in between
    assert d.wl_arr is not None, "`applied: True` while acquire would still refuse"
    assert d.wl_arr.shape == (2560,)
    # The stubbed fit's coefficients evaluated at pixel 0. What this
    # test is about is that the axis was replaced at all, without a
    # reconnect -- not what value it took.
    assert d.wl_arr[0] == pytest.approx(433.2, abs=0.1)


def test_a_failed_calibration_leaves_the_live_axis_alone(tmp_path, monkeypatch):
    """A bad fit must not blank an axis that was working."""
    d = _driver(tmp_path)
    _stub_fit(monkeypatch, fit_rms_nm=99.0, max_residual_nm=99.0)
    wlc.save(CALIB, d.calibration_file())
    d.wl_arr = d._wavelengths()
    before = d.wl_arr.copy()
    monkeypatch.setattr(
        d,
        "_capture_lamp_frame",
        lambda n_frames, exp_time: _fake_lamp_frame(2560, [200]),
    )

    resp = d.run_wl_calibration(ANCHORS)

    assert resp.response == "failed"
    np.testing.assert_array_equal(d.wl_arr, before)


def _good_calibration_args():
    """Line pixels and their true wavelengths for a fit that should pass."""
    line_pixels = [200, 700, 1300, 1900, 2400]
    return line_pixels, [400.0 + 0.2 * p for p in line_pixels]


def test_too_few_anchors_is_refused_not_defaulted(tmp_path, monkeypatch):
    """The route default is `anchors: list = []`, which reaches here as None.

    There is no default anchor set and there cannot be one: an anchor names a
    pixel on THIS detector at THIS grating, which no table can know. The
    refusal fires before the lamp is even exposed.
    """
    d = _driver(tmp_path)
    exposed = {"n": 0}

    def _count(n_frames, exp_time):
        exposed["n"] += 1
        return _fake_lamp_frame(2560, [200])

    monkeypatch.setattr(d, "_capture_lamp_frame", _count)
    for empty in (None, [], [[100, 450.0]]):
        resp = d.run_wl_calibration(empty)
        assert resp.response == "failed"
        assert "anchors" in resp.message
        assert not d.calibration_file().exists()
    assert exposed["n"] == 0, "refused before exposing the lamp"


def test_a_fit_worse_than_the_limit_is_not_saved(tmp_path, monkeypatch):
    """A garbage fit must not overwrite the calibration it replaces.

    A cosmic-ray spike brighter than the lamp lines displaces the weakest
    real line from `find_peaks`' selection, so a peak is paired with the
    wrong reference wavelength. Nothing raises and `n_lines` is still 5; the
    residual is the only evidence there is.
    """
    d = _driver(tmp_path)
    _stub_fit(monkeypatch, fit_rms_nm=5.0, max_residual_nm=9.0)
    wlc.save(CALIB, d.calibration_file())
    before = d.calibration_file().read_bytes()
    line_pixels, true_nm = _good_calibration_args()

    def _spiked(n_frames, exp_time):
        counts = _fake_lamp_frame(2560, line_pixels)
        counts[1000] += 50000.0
        return counts

    monkeypatch.setattr(d, "_capture_lamp_frame", _spiked)

    resp = d.run_wl_calibration(ANCHORS)

    assert resp.response == "failed"
    assert resp.data["fit_rms_nm"] > 0.5
    assert resp.data["max_fit_rms_nm"] == 0.5
    assert resp.data["applied"] is False
    assert f"{resp.data['fit_rms_nm']:.4f}" in resp.message
    assert "0.5000" in resp.message
    assert d.calibration_file().read_bytes() == before, "the good record was lost"
    assert (
        not d.calibration_file().with_name(d.calibration_file().name + ".prev").exists()
    ), "a refused fit must not even rotate the backup"


def test_the_rms_limit_is_the_callers_to_set(tmp_path, monkeypatch):
    """Same measurement, looser limit: it must be the gate doing the refusing."""
    d = _driver(tmp_path)
    _stub_fit(monkeypatch, fit_rms_nm=99.0, max_residual_nm=99.0)
    line_pixels, true_nm = _good_calibration_args()

    def _spiked(n_frames, exp_time):
        counts = _fake_lamp_frame(2560, line_pixels)
        counts[1000] += 50000.0
        return counts

    monkeypatch.setattr(d, "_capture_lamp_frame", _spiked)

    assert d.run_wl_calibration(ANCHORS).response == "failed"
    # Same stubbed measurement, a limit loose enough to admit it: the gate is
    # what refused, not the fit.
    resp = d.run_wl_calibration(ANCHORS, max_fit_rms_nm=1e6)
    assert resp.response == "success"


def test_a_non_monotonic_axis_is_refused_however_tight_the_fit(tmp_path, monkeypatch):
    """rms is blind to this: the fit is exact AT the lines and turns over between.

    Two pixels claiming the same wavelength is not an axis, and the spectrum
    it produces looks entirely ordinary.
    """
    d = _driver(tmp_path)
    _stub_fit(monkeypatch, coeffs=[660.0, 232.0, -400.0, 0.0, 0.0])
    line_pixels = [700, 1200, 1700, 2100, 2500]
    turning = [1e-9 * p**3 + 1.05e-6 * p**2 - 9e-4 * p + 400.0 for p in line_pixels]
    monkeypatch.setattr(
        d,
        "_capture_lamp_frame",
        lambda n_frames, exp_time: _fake_lamp_frame(2560, line_pixels),
    )

    resp = d.run_wl_calibration(ANCHORS)

    assert resp.response == "failed"
    assert "monotonic" in resp.message
    assert resp.data["fit_rms_nm"] < 0.5, "this fixture must clear the rms gate"
    assert not d.calibration_file().exists()
    assert d.wl_arr is None, "a refused fit must not become the live axis"


def test_an_overwrite_keeps_the_previous_calibration(tmp_path, monkeypatch):
    d = _driver(tmp_path)
    _stub_fit(monkeypatch)
    wlc.save(CALIB, d.calibration_file())
    line_pixels, true_nm = _good_calibration_args()
    monkeypatch.setattr(
        d,
        "_capture_lamp_frame",
        lambda n_frames, exp_time: _fake_lamp_frame(2560, line_pixels),
    )

    assert d.run_wl_calibration(ANCHORS).response == "success"

    prev = d.calibration_file().with_name(d.calibration_file().name + ".prev")
    assert prev.exists()
    assert wlc.load(prev) == CALIB


def test_a_saved_calibration_records_which_variant_wrote_it(tmp_path, monkeypatch):
    d = _driver(tmp_path)
    _stub_fit(monkeypatch)
    line_pixels, true_nm = _good_calibration_args()
    monkeypatch.setattr(
        d,
        "_capture_lamp_frame",
        lambda n_frames, exp_time: _fake_lamp_frame(2560, line_pixels),
    )
    assert d.run_wl_calibration(ANCHORS).response == "success"
    assert wlc.load(d.calibration_file()).wl_source == "calibration"


def _write_calib(driver, **overrides):
    fields = dict(
        model=wlc.MODEL_POLY,
        coeffs=[400.0, 0.2],
        n_pixels=16,
        fit_rms_nm=0.02,
        n_lines=5,
        lamp="Hg-Ar",
        created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source_action_uuid=None,
        wl_source="calibration",
    )
    fields.update(overrides)
    wlc.save(wlc.WavelengthCalibration(**fields), driver.calibration_file())


def test_a_spectrograph_written_record_warns_when_loaded_here(tmp_path, caplog):
    """Both variants write one filename, so this is the only thing that notices.

    A station that measured a lamp for comparison, changed gratings, then
    flipped to `wl_source: calibration` otherwise adopts a fit taken under
    different optics with nothing said.
    """
    d = _driver(tmp_path)
    _write_calib(d, wl_source="spectrograph")
    with caplog.at_level("WARNING"):
        assert d._wavelengths() is not None
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("wl_source" in m and "spectrograph" in m for m in warnings), warnings


def test_a_record_predating_the_field_warns_as_unknown(tmp_path, caplog):
    """It still loads -- refusing would strand a legitimately calibrated station."""
    d = _driver(tmp_path)
    _write_calib(d, wl_source="unknown")
    with caplog.at_level("WARNING"):
        assert d._wavelengths() is not None
    assert any(
        "wl_source" in r.getMessage() and "unknown" in r.getMessage()
        for r in caplog.records
        if r.levelname == "WARNING"
    )


def test_a_calibration_written_here_warns_about_nothing(tmp_path, caplog):
    """The warnings must be about provenance, not fire on every load."""
    d = _driver(tmp_path)
    _write_calib(d)
    with caplog.at_level("WARNING"):
        assert d._wavelengths() is not None
    assert [r.getMessage() for r in caplog.records if r.levelname == "WARNING"] == []


def test_a_calibration_older_than_the_limit_warns_with_its_age(tmp_path, caplog):
    d = _driver(tmp_path)
    old = datetime.now(timezone.utc) - timedelta(days=200)
    _write_calib(d, created=old.isoformat(timespec="seconds"))
    with caplog.at_level("WARNING"):
        assert d._wavelengths() is not None
    assert any(
        "200 days old" in r.getMessage()
        for r in caplog.records
        if r.levelname == "WARNING"
    ), [r.getMessage() for r in caplog.records]


def test_an_unreadable_created_stamp_does_not_cost_the_axis(tmp_path, caplog):
    """The age check is a nicety; the wavelength axis is not."""
    d = _driver(tmp_path)
    _write_calib(d, created="not a date")
    with caplog.at_level("WARNING"):
        wl = d._wavelengths()
    assert wl is not None and wl.shape == (16,)


def test_connect_warns_when_the_axis_does_not_span_the_detector(
    tmp_path, monkeypatch, caplog
):
    """A calibration recorded at one AOI width, applied at another.

    The header's `optional.wl` then has a different length from the `ch_*`
    columns beside it, and nothing downstream compares the two.
    """

    class _FakeSDK:
        def GetCamera(self, dev_id):
            return object()

    monkeypatch.setattr(andor_driver, "_load_camera", lambda: None)
    monkeypatch.setattr(andor_driver, "AndorSDK3", _FakeSDK, raising=False)

    d = _driver(tmp_path)
    wlc.save(CALIB, d.calibration_file())  # 16 pixels
    monkeypatch.setattr(d, "setup_image", lambda: 6.5)
    monkeypatch.setattr(d, "get_meta_data", lambda: (2560, 2160, 1, 1e8))

    with caplog.at_level("WARNING"):
        assert d.connect().response == "success"

    assert any(
        "16 points" in r.getMessage() and "2560" in r.getMessage()
        for r in caplog.records
        if r.levelname == "WARNING"
    ), [r.getMessage() for r in caplog.records]


def test_connect_says_nothing_when_the_axis_matches(tmp_path, monkeypatch, caplog):
    class _FakeSDK:
        def GetCamera(self, dev_id):
            return object()

    monkeypatch.setattr(andor_driver, "_load_camera", lambda: None)
    monkeypatch.setattr(andor_driver, "AndorSDK3", _FakeSDK, raising=False)

    d = _driver(tmp_path)
    _write_calib(d, n_pixels=2560)
    monkeypatch.setattr(d, "setup_image", lambda: 6.5)
    monkeypatch.setattr(d, "get_meta_data", lambda: (2560, 2160, 1, 1e8))

    with caplog.at_level("WARNING"):
        assert d.connect().response == "success"

    assert [r.getMessage() for r in caplog.records if r.levelname == "WARNING"] == []
