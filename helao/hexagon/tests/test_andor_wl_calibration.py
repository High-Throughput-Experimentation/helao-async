"""Pure wavelength-calibration numerics and persistence.

No vendor SDK and no HELAO server are involved, so this whole file runs on
Linux with nothing installed. That is the point of keeping the numerics in
their own module: the part most likely to need iteration is the part that
needs no hardware to iterate on.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from helao.deploy.hte.drivers.spec.andor import wl_calibration as wlc


def _synthetic_lamp(coeffs, n_pixels, line_pixels, width=2.0):
    """A spectrum with Gaussian peaks at `line_pixels`, flat elsewhere."""
    pixels = np.arange(n_pixels, dtype=float)
    counts = np.full(n_pixels, 100.0)
    for p in line_pixels:
        counts += 5000.0 * np.exp(-0.5 * ((pixels - p) / width) ** 2)
    return counts


TRUE_COEFFS = [400.0, 0.2, 1e-6, 0.0]
N_PIXELS = 2560
LINE_PIXELS = [200, 700, 1300, 1900, 2400]


def _true_nm(pixel):
    return sum(c * pixel**i for i, c in enumerate(TRUE_COEFFS))


def test_evaluate_reproduces_the_polynomial():
    calib = wlc.WavelengthCalibration(
        model=wlc.MODEL_POLY,
        coeffs=TRUE_COEFFS,
        n_pixels=8,
        fit_rms_nm=0.0,
        n_lines=0,
        lamp="none",
        created="2026-09-04T00:00:00Z",
        source_action_uuid=None,
    )
    wl = wlc.evaluate(calib)
    assert wl.shape == (8,)
    assert wl[0] == pytest.approx(_true_nm(0))
    assert wl[7] == pytest.approx(_true_nm(7))


def test_fit_recovers_a_known_polynomial():
    counts = _synthetic_lamp(TRUE_COEFFS, N_PIXELS, LINE_PIXELS)
    lines = [_true_nm(p) for p in LINE_PIXELS]
    calib = wlc.fit_wavelength(counts, lines, degree=3, lamp="synthetic")

    assert calib.model == wlc.MODEL_POLY
    assert calib.n_pixels == N_PIXELS
    assert calib.n_lines == len(LINE_PIXELS)
    assert calib.lamp == "synthetic"
    assert calib.fit_rms_nm < 0.5

    wl = wlc.evaluate(calib)
    for p in LINE_PIXELS:
        assert wl[p] == pytest.approx(_true_nm(p), abs=1.0)


def test_fit_refuses_when_peaks_and_lines_disagree_in_count():
    counts = _synthetic_lamp(TRUE_COEFFS, N_PIXELS, LINE_PIXELS)
    with pytest.raises(ValueError, match="line"):
        wlc.fit_wavelength(counts, [400.0, 500.0], degree=3)


def test_fit_refuses_a_degree_it_cannot_support():
    counts = _synthetic_lamp(TRUE_COEFFS, N_PIXELS, LINE_PIXELS)
    lines = [_true_nm(p) for p in LINE_PIXELS]
    with pytest.raises(ValueError, match="degree"):
        wlc.fit_wavelength(counts, lines, degree=9)


def test_round_trip_through_disk(tmp_path):
    calib = wlc.WavelengthCalibration(
        model=wlc.MODEL_POLY,
        coeffs=TRUE_COEFFS,
        n_pixels=N_PIXELS,
        fit_rms_nm=0.01,
        n_lines=5,
        lamp="Hg-Ar",
        created="2026-09-04T00:00:00Z",
        source_action_uuid="abc-123",
    )
    path = tmp_path / "calib.json"
    wlc.save(calib, path)
    assert wlc.load(path) == calib


def test_load_refuses_an_unknown_model(tmp_path):
    """A record this build cannot evaluate must not be silently mis-read."""
    path = tmp_path / "calib.json"
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
    with pytest.raises(wlc.UnknownCalibrationModel, match="chebyshev"):
        wlc.load(path)


def test_save_writes_readable_json(tmp_path):
    """The record is meant to be diagnosed by eye in a station's STATES dir."""
    calib = wlc.WavelengthCalibration(
        model=wlc.MODEL_POLY,
        coeffs=[1.0, 2.0],
        n_pixels=2,
        fit_rms_nm=0.5,
        n_lines=2,
        lamp="Hg-Ar",
        created="2026-09-04T00:00:00Z",
        source_action_uuid=None,
    )
    path = tmp_path / "calib.json"
    wlc.save(calib, path)
    loaded = json.loads(path.read_text())
    assert loaded["lamp"] == "Hg-Ar"
    assert loaded["fit_rms_nm"] == 0.5
    assert "\n" in path.read_text(), "expected indented JSON, not one line"


def test_calibration_path_follows_the_station_convention():
    p = wlc.calibration_path("/root/STATES", "hte-eche-11", "ANDOR")
    assert p == Path("/root/STATES/hte-eche-11_ANDOR_andor_wl_calib.json")


def test_module_imports_no_vendor_or_server_package():
    """Keeping this module pure is what lets it be iterated on Linux."""
    src = Path(wlc.__file__).read_text()
    for banned in ("pyAndor", "helao.core", "helao.helpers", "fastapi"):
        assert banned not in src, f"{banned} must not appear in wl_calibration.py"
