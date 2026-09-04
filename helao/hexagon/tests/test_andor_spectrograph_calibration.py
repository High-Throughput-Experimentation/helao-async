"""A spectrograph station may measure a lamp; it just does not use it live.

This is the cross-check that validates the new path against the old one
before any station is switched over.
"""

import numpy as np

from helao.deploy.hte.drivers.spec.andor.spectrograph import AndorSpectrographDriver


def _fake_lamp_frame(n_pixels, line_pixels):
    pixels = np.arange(n_pixels, dtype=float)
    counts = np.full(n_pixels, 100.0)
    for p in line_pixels:
        counts += 5000.0 * np.exp(-0.5 * ((pixels - p) / 2.0) ** 2)
    return counts


def test_a_spectrograph_station_can_calibrate_but_does_not_apply_it(
    tmp_path, monkeypatch
):
    d = AndorSpectrographDriver(
        config={"states_root": str(tmp_path), "host": "teststation"},
        server_key="ANDOR",
    )
    line_pixels = [200, 700, 1300, 1900, 2400]
    true_nm = [400.0 + 0.2 * p for p in line_pixels]
    monkeypatch.setattr(
        d,
        "_capture_lamp_frame",
        lambda n_frames, exp_time: _fake_lamp_frame(2560, line_pixels),
    )

    resp = d.run_wl_calibration(true_nm, lamp="Hg-Ar", degree=1)
    assert resp.response == "success"
    assert resp.data["applied"] is False, "the spectrograph remains the live axis"
    assert d.calibration_file().exists()


def test_capture_averages_frames_by_summing_down_the_spatial_axis(
    tmp_path, monkeypatch
):
    """``acquisition.image`` is a 2-D detector frame, not a spectrum.

    Not stubbed away, because reading it as 1-D is the mistake that would
    silently calibrate against a single detector row.
    """
    d = AndorSpectrographDriver(config={"states_root": str(tmp_path)})

    class _Acq:
        def __init__(self, image):
            self.image = image

    images = [np.tile(np.arange(8.0), (4, 1)), np.tile(np.arange(8.0), (4, 1)) * 3.0]
    calls = iter(images)
    monkeypatch.setattr(
        d,
        "image_and_check_dynamic_range",
        lambda exposure_time: (_Acq(next(calls)), 0, True, 1.0),
    )

    counts = d._capture_lamp_frame(2, 0.0098)
    # each frame sums 4 identical rows, then the two frames are averaged
    np.testing.assert_allclose(counts, np.arange(8.0) * 4.0 * 2.0)


def test_a_one_dimensional_acquisition_is_refused(tmp_path, monkeypatch):
    d = AndorSpectrographDriver(config={"states_root": str(tmp_path)})

    class _Acq:
        image = np.arange(8.0)

    monkeypatch.setattr(
        d,
        "image_and_check_dynamic_range",
        lambda exposure_time: (_Acq(), 0, True, 1.0),
    )
    # surfaced as a failed DriverResponse, never as an exception at the handler
    resp = d.run_wl_calibration([400.0, 500.0, 600.0, 700.0, 800.0], degree=1)
    assert resp.response == "failed"


def test_a_spectrograph_station_keeps_its_live_axis_after_calibrating(
    tmp_path, monkeypatch
):
    """The refresh is gated on `uses_lamp_calibration`, and must stay gated.

    Ungated it would be worse than a no-op here: this variant's
    `_wavelengths()` re-drives the ATSpectrograph, so refreshing would open a
    vendor handle and reset the grating/slit/ND mid-run to compute an axis
    the station does not use.
    """
    d = AndorSpectrographDriver(
        config={"states_root": str(tmp_path), "host": "teststation"},
        server_key="ANDOR",
    )
    sentinel = np.linspace(300.0, 800.0, 2560)
    d.wl_arr = sentinel
    line_pixels = [200, 700, 1300, 1900, 2400]
    true_nm = [400.0 + 0.2 * p for p in line_pixels]
    monkeypatch.setattr(
        d,
        "_capture_lamp_frame",
        lambda n_frames, exp_time: _fake_lamp_frame(2560, line_pixels),
    )

    def _must_not_be_called():
        raise AssertionError("_wavelengths() re-drives the spectrograph hardware")

    monkeypatch.setattr(d, "_wavelengths", _must_not_be_called)

    resp = d.run_wl_calibration(true_nm, lamp="Hg-Ar", degree=1)

    # An ungated refresh trips `_must_not_be_called`, which run_wl_calibration
    # swallows into a `failed` response -- so this line, not the wl_arr one, is
    # what catches the regression.
    assert resp.response == "success"
    assert resp.data["applied"] is False
    assert d.wl_arr is sentinel, "the spectrograph's live axis was replaced"


def test_a_comparison_fit_records_that_it_is_one(tmp_path, monkeypatch):
    """The two variants write one filename, so the record has to say which.

    Without it, a station that measured a lamp here for comparison, changed
    gratings, then flipped to ``wl_source: calibration`` adopts this fit as
    its live axis with nothing anywhere saying it was never meant to be one.
    """
    from helao.deploy.hte.drivers.spec.andor import wl_calibration as wlc

    d = AndorSpectrographDriver(
        config={"states_root": str(tmp_path), "host": "teststation"},
        server_key="ANDOR",
    )
    line_pixels = [200, 700, 1300, 1900, 2400]
    monkeypatch.setattr(
        d,
        "_capture_lamp_frame",
        lambda n_frames, exp_time: _fake_lamp_frame(2560, line_pixels),
    )

    resp = d.run_wl_calibration(
        [400.0 + 0.2 * p for p in line_pixels], lamp="Hg-Ar", degree=1
    )

    assert resp.response == "success"
    assert wlc.load(d.calibration_file()).wl_source == "spectrograph"
